"""
Main logic for the bot.

Author: eliaise
"""

import logging
from configparser import ConfigParser
import mysql.connector
from telegram import (
    Update,
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from re import search

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# mysql connection
connection = None

# conversation states
NAME, TITLE, DEPARTMENT, RESTART, ERROR, CANCEL = range(6)

# telegram
bot_token = None
drive_token = None


async def notify(user_id: int, name: str, title: str, department: str) -> bool:
    """Notifies the relevant person in-charge that there is an outstanding registration request"""
    logger.info("Sending notification to person in-charge of {} department.".format(department))
    bot = Bot(bot_token)

    # find the person in-charge
    query = "SELECT userId FROM users where department = %s and role = 'IC'"
    result = run_select(query, (department, ))

    if result:
        # contact this IC
        ic = result[0]
        await bot.send_message(chat_id=ic, text="{} {} is requesting to join your team.".format(title, name))
    else:
        # contact an admin
        query = "SELECT userId FROM users where role = 'Admin' LIMIT 1"
        result = run_select(query, None)
        if not result:
            logger.error("No admin found.")
            return False

        admin = result[0]
        await bot.send_message(chat_id=admin,
                               text="{} {} is requesting to join the {} department.".format(title, name, department))

    return True


def finish(user_id, name, title, department) -> bool:
    """Finish the registration process."""
    logger.info("Finishing registration for user {}.".format(user_id))

    # finish registration
    logger.info("Finishing registration for user {}".format(user_id))
    query = "INSERT INTO users VALUES (%s, %s, %s, %s, %s, %s)"
    return run_insert(query, (user_id, name, title, department, "User", 0))


async def handle_error(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Give an error message as a response"""
    logger.info("Unknown exception was caught.")
    await update.message.reply_text("An exception was caught. Please contact the administrator for help.")
    return ConversationHandler.END


async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Give a cancellation message"""
    logger.info("Cancelling registration process.")
    await update.message.reply_text("Stopping the registration process.")
    return ConversationHandler.END


async def handle_department(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the user's department."""
    user_id = update.message.from_user.id
    department = update.message.text

    # test whether the department is valid
    match = search("^[a-zA-Z0-9 ]{2,5}$", department)
    if not match:
        logger.info("User {} submitted an invalid department. Restarting...")
        await update.message.reply_text("Department given is invalid. "
                                        "Please give a valid department. E.g. IT")
        return DEPARTMENT

    logger.info("Saving {} as the department for user {}".format(department, user_id))
    context.user_data["department"] = department
    await update.message.reply_text("Okay! Finalising registration.")
    success = finish(
        user_id,
        context.user_data["name"],
        context.user_data["title"],
        context.user_data["department"]
    )

    if not success:
        await update.message.reply_text("An exception was caught. Please contact the administrator for help.")
    else:
        await update.message.reply_text("Successfully registered you into the database. "
                                        "Please wait a few hours for approval.")

    # notify the IC to approve the request
    result = await notify(
        user_id,
        context.user_data["name"],
        context.user_data["title"],
        context.user_data["department"])
    if not result:
        logger.info("Failed to find someone to notify.")

    return ConversationHandler.END


async def handle_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the user's title number."""
    user_id = update.message.from_user.id
    title = update.message.text.upper()

    # test whether this title is valid
    match = search("^[A-Z0-9]{3,4}$", title)
    if not match:
        logger.info("User {} submitted an invalid title. Restarting...")
        await update.message.reply_text("Title given is invalid. "
                                        "Please give a valid title. E.g. exec")
        return TITLE

    logger.info("Saving {} as the title for user {}".format(title, user_id))
    context.user_data["title"] = title
    await update.message.reply_text("What is your department?")
    return DEPARTMENT


async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the user's name."""
    user_id = update.message.from_user.id
    name = update.message.text

    # test whether this name is valid
    match = search("^[a-zA-Z ]{1,100}$", name)
    if not match:
        logger.info("User {} submitted an invalid name. Restarting...")
        await update.message.reply_text("Name given contains invalid characters or is too long. "
                                        "Please give a valid name.")
        return NAME

    logger.info("Saving {} as the name for user {}".format(name, user_id))
    context.user_data["name"] = name
    await update.message.reply_text("What is your title?")
    return TITLE


async def handle_register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the registration process of the user."""
    # get user's telegram id
    user_id = update.message.from_user.id
    logger.info("Starting user registration for user {}".format(user_id))

    # check if this user exists in database
    query = "SELECT name, accStatus FROM users WHERE userId = %s"
    result = run_select(query, (user_id, ))

    if result:
        logger.info("User {} exists in database".format(user_id))
        name, acc_status = result[0]
        if not acc_status:
            logger.info("User {}'s account is pending approval")
            await update.message.reply_text(
                "Hello {}. You have already been registered into the database.".format(name))
        else:
            await update.message.reply_text("Hello {}. Your account is pending approval. "
                                            "Please check back in a few hours.".format(name))
        return ConversationHandler.END

    # user does not exist in database, query user for information
    await update.message.reply_text("Welcome! We'll begin the registration process. "
                                    "Do a /cancel at any time to exit the registration process. "
                                    "Please give me your name. Only alphabets and spaces are allowed.")
    return NAME


async def display_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prints out the help message."""
    await update.message.reply_text("This bot is updates your attendance. "
                                    "/register: starts the registration process "
                                    "/update <status>: sets your status for the day"
                                    "/pull: displays the attendance of all members in your department "
                                    "/role <role> <user>: sets the role of the target user "
                                    "/help: prints this message")


def run_select(stmt: str, variables: tuple) -> list:
    """Run a select statement."""
    logger.info("SELECT query sent to database: {}".format(stmt))

    try:
        with connection.cursor() as cursor:
            cursor.execute(stmt, variables)
            result = cursor.fetchall()
    except Exception as e:
        logger.exception(e)

    return result


def run_insert(stmt: str, variables: tuple) -> bool:
    """Run an insert statement"""
    logger.info("INSERT query sent to database: {}".format(stmt))

    try:
        with connection.cursor() as cursor:
            cursor.execute(stmt, variables)
            connection.commit()
    except Exception as e:
        logger.exception(e)
        return False

    return True


def run_update(stmt: str, variables: tuple) -> bool:
    """Run an update statement"""
    logger.info("UPDATE query sent to database: {}".format(stmt))

    try:
        with connection.cursor() as cursor:
            cursor.execute(stmt, variables)
            connection.commit()
    except Exception as e:
        logger.exception(e)
        return False

    return True


def main() -> None:
    """Starts the bot."""
    global connection, bot_token, drive_token

    # Read the config file
    config = ConfigParser()
    config.read("config/init.ini")
    bot_token = config["Telegram"]["BOT_TOKEN"]
    drive_token = config["Google"]["DRIVE_TOKEN"]
    db_host = config["MySQL"]["HOST"]
    db_user = config["MySQL"]["USER"]
    db_pass = config["MySQL"]["PASS"]
    db_name = config["MySQL"]["NAME"]

    # connect to database
    try:
        connection = mysql.connector.connect(
            host=db_host,
            user=db_user,
            password=db_pass,
            database=db_name
        )
    except Exception as e:
        logger.exception(e)
        exit(1)

    # start telegram application object
    application = Application.builder().token(bot_token).build()

    application.add_handler(CommandHandler("help", display_help))
    registration_handler = ConversationHandler(
        entry_points=[CommandHandler("register", handle_register)],
        states={
            NAME: [MessageHandler(filters.TEXT, handle_name)],
            TITLE: [MessageHandler(filters.TEXT, handle_title)],
            DEPARTMENT: [MessageHandler(filters.TEXT, handle_department)],
            RESTART: [CommandHandler("restart", handle_register)],
            ERROR: [CommandHandler("error", handle_error)],
            CANCEL: [CommandHandler("cancel", handle_cancel)]
        },
        fallbacks=[MessageHandler(filters.TEXT, handle_error)]
    )

    application.add_handler(registration_handler)

    # poll for updates
    application.run_polling()


if __name__ == "__main__":
    main()
