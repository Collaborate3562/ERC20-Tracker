import asyncio
import pandas as pd
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from config import TELEGRAM_API_TOKEN, CSV_FILE_PATH, TELEGRAM_CHAT_ID, INFURA_API_KEY, ETHERSCAN_API_KEY
from web3 import Web3, HTTPProvider
import requests
import json
from datetime import datetime, timedelta

# Set up logging
logging.basicConfig(level=logging.INFO)

# Set up Web3 and Infura API
INFURA_URL = f"https://mainnet.infura.io/v3/{INFURA_API_KEY}"
w3 = Web3(HTTPProvider(INFURA_URL))

# Set up Telegram bot
bot = Bot(token=TELEGRAM_API_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

# Function to load CSV file with wallet addresses and nicknames
def load_csv(file_path):
    df = pd.read_csv(file_path)
    df = df.rename(columns={"Address": "wallets"})
    return df

# Function to get ERC-20 token transactions for a given wallet address
async def get_erc20_transactions(address):
    transfer_event_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    from_block = w3.eth.block_number - 100  # Adjust this value to set how many blocks back to check for transactions

    filter_params = {
        "fromBlock": from_block,
        "toBlock": "latest",
        "topics": [transfer_event_topic, None, None],
        "address": address
    }

    logs = w3.eth.get_logs(filter_params)
    return logs

# Function to get ETH transactions for a given wallet address
async def get_eth_transactions(address):
    from_block = w3.eth.block_number - 100
    api_endpoint = f"https://api.etherscan.io/api?module=account&action=txlist&address={address}&startblock={from_block}&endblock=latest&page=1&offset=10&sort=desc&apikey={ETHERSCAN_API_KEY}"

    response = requests.get(api_endpoint)
    transactions = response.json()["result"]

    relevant_transactions = [tx for tx in transactions if tx["to"].lower() == address.lower() or tx["from"].lower() == address.lower()]

    return relevant_transactions



# Function to monitor transactions for all wallets in the CSV file
async def monitor_tokens():
    # Load CSV file with wallet addresses and nicknames
    df = load_csv(CSV_FILE_PATH)
    addresses = [row["wallets"] for _, row in df.iterrows()]  # Get addresses from csv
    address_nicknames = {row["wallets"]: row["nickname"] for _, row in df.iterrows()}  # Get address nicknames
        
    # Initialize dictionary to keep track of last transactions for each address and token type
    last_transactions = {}
    for address in addresses:
        last_transactions[address] = {"erc20": None, "eth": None}

    while True:
        for address in addresses:
            transactions = await get_erc20_transactions(address)
            eth_transactions = await get_eth_transactions(address)

            nickname = ""  # Initialize nickname variable
            action = ""  # Initialize action variable

            # Handle erc20 transactions
            for tx in transactions:
                tx_hash = tx["transactionHash"].hex()
                if tx_hash != last_transactions[address]["erc20"]:
                    last_transactions[address]["erc20"] = tx_hash

                    tx_data = w3.eth.get_transaction(tx_hash)
                    input_data = tx_data["input"]

                    if len(input_data) >= 138:
                        to_address = input_data[34:74]
                        value = int(input_data[74:], 16) / (10 ** 18)

                        from_address = tx_data["from"].lower()
                        to_address = f"0x{to_address}".lower()

                        if from_address in addresses and to_address in addresses:
                            continue
                        elif from_address in addresses:
                            action = "sent"
                            nickname = address_nicknames[from_address.lower()]
                        elif to_address in addresses:
                            action = "received"
                            nickname = address_nicknames[to_address.lower()]

                        message = f"{nickname} ({from_address if action == 'sent' else to_address}) {action} {value} tokens"
                        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)

            # Handle ETH transactions
            for tx in eth_transactions:
                if tx != last_transactions[address]["eth"]:
                    last_transactions[address]["eth"] = tx

                    tx_data = w3.eth.get_transaction(tx)

                    value = tx_data["value"] / (10 ** 18)

                    from_address = tx_data["from"].lower()
                    to_address = tx_data["to"].lower()

                    if from_address in addresses:
                        action = "sent"
                        nickname = address_nicknames[from_address.lower()]
                    elif to_address in addresses:
                        action = "received"
                        nickname = address_nicknames[to_address.lower()]

                    message = f"{nickname} ({from_address if action == 'sent' else to_address}) {action} {value} ETH"
                    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)

        await asyncio.sleep(60)  # Adjust the monitoring frequency as needed.

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    await message.reply("This Bot tracks activity in insidooor's wallets."
                        "to be added etherscan link to the message"
                        "to be added dextool chart link to the erc20 token")


if __name__ == '__main__':
    from aiogram import executor

    async def on_startup(dp):
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="Bot has been started")
        asyncio.create_task(monitor_tokens())  # Run monitor_tokens as a background task

    async def on_shutdown(dp):
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="Bot has been stopped")

    executor.start_polling(dp, on_startup=on_startup, on_shutdown=on_shutdown)