import os
from flask import Flask, request
from formsg import decrypt_content
import sqlite3
import requests
from dotenv import load_dotenv
import logging

try:
    load_dotenv()
except:
    logging.error("No .env file found")


BOT_API_KEY = os.environ["BOT_API_KEY"]
MY_CHANNEL_NAME = os.environ["MY_CHANNEL_NAME"]
SECRET_KEY = os.environ["SECRET_KEY"]

# Create table Loan(Name, Equipment, Quantity) if doesnt exist
with sqlite3.connect("database.db") as conn:
    cursor = conn.cursor()
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS `loan` (
        `name` TEXT,
        `equipment` TEXT,
        `qty` INT,
        `unit` TEXT,
        PRIMARY KEY (`name`,`equipment`)
    );"""
    )
    conn.commit()


app = Flask(__name__)


@app.route("/webhook", methods=["POST"])
def webhook_handler():
    encrypted_content = dict(request.json)
    contents = decrypt_content(encrypted_content, SECRET_KEY)

    # Set the drawee name based on if it is external or not
    drawee = (
        contents[0]["answer"]
        if contents[0]["answer"] != "External"
        else contents[1]["answer"].strip().upper()
    )

    unit = contents[2]["answer"].strip().upper()

    # Transaction type (Draw Out or Return)
    type = contents[3]["answer"]

    equipment = {i[0]: int(i[1]) for i in contents[4]["answerArray"]}
    logging.info(f"Drawee: {drawee}, Transaction Type: {type}, Equipment: {equipment}")
    if type == "Draw Out":
        # Add to DB
        with sqlite3.connect("database.db") as conn:
            cursor = conn.cursor()
            for eq in equipment.keys():
                # Check if equipment and name pair exists
                cursor.execute(
                    "SELECT `qty` FROM `loan` WHERE `name` = ? AND `equipment` = ?;",
                    (drawee, eq),
                )
                result = cursor.fetchone()
                if result is None:
                    cursor.execute(
                        """
                    INSERT INTO `loan` (`name`, `equipment`, `qty`, `unit`)
                    VALUES (?, ?, ?, ?);
                    """,
                        (drawee, eq, equipment[eq], unit),
                    )
                else:
                    cursor.execute(
                        """
                    UPDATE `loan`
                    SET `qty` = ?
                    WHERE `name` = ? AND `equipment` = ?;
                """,
                        (result[0] + equipment[eq], drawee, eq),
                    )
            conn.commit()
    else:
        # Remove from DB
        with sqlite3.connect("database.db") as conn:
            cursor = conn.cursor()
            for eq in equipment.keys():
                # Calculate new quantity
                cursor.execute(
                    "SELECT `qty` FROM `loan` WHERE `name` = ? AND `equipment` = ?;",
                    (drawee, eq),
                )
                result = cursor.fetchone()
                if result is None:
                    continue
                old_qty = result[0]
                if old_qty - equipment[eq] <= 0:
                    cursor.execute(
                        "DELETE FROM `loan` WHERE `name` = ? AND `equipment` = ?;",
                        (drawee, eq),
                    )
                else:
                    cursor.execute(
                        """
                    UPDATE `loan`
                    SET `qty` = ?
                    WHERE `name` = ? AND `equipment` = ?;
                """,
                        (old_qty - equipment[eq], drawee, eq),
                    )
            conn.commit()

    # Create telegram message
    MY_MESSAGE_TEXT = "<b>Equipment Accounting</b>\n\n"

    # Query DB to find out who has what equipment
    with sqlite3.connect("database.db") as conn:
        cursor = conn.cursor()
        # Get unique names
        cursor.execute("SELECT DISTINCT `name`, `unit` FROM `loan`")
        names = [
            [i[0], f"{i[0]} {'(' + i[1] + ')' if i[1] is not None else ''}"]
            for i in cursor.fetchall()
        ]

        for name, formatted_name in names:
            MY_MESSAGE_TEXT += f"<b>{formatted_name.strip()}</b>\n"
            cursor.execute(
                "SELECT `equipment`, `qty` FROM `loan` WHERE `name` = ?;", (name,)
            )
            result = cursor.fetchall()
            for eq in result:
                MY_MESSAGE_TEXT += f"{eq[0]} x {eq[1]}\n"
            MY_MESSAGE_TEXT += "\n"

    # Last updated by
    MY_MESSAGE_TEXT += f"Last updated by {encrypted_content['data']['submissionId']}"

    response = requests.get(
        f"https://api.telegram.org/bot{BOT_API_KEY}/sendMessage",
        data={
            "chat_id": MY_CHANNEL_NAME,
            "text": MY_MESSAGE_TEXT,
            "parse_mode": "HTML",
        },
    )

    return "Success", 200


@app.route("/")
def root():
    return "Online", 200


@app.route("/database")
def database():
    with sqlite3.connect("database.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM `loan`")
        data = cursor.fetchall()
    return data, 200


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
