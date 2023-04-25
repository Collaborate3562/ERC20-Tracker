import asyncio
import pandas as pd
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from config import TELEGRAM_API_TOKEN, CSV_FILE_PATH, TELEGRAM_CHAT_ID, INFURA_API_KEY, ETHERSCAN_API_KEY
from web3 import Web3, HTTPProvider
from web3._utils.abi import decode_hex
from eth_abi import abi
import requests
import json
from datetime import datetime, timedelta

# Set up logging
logging.basicConfig(level=logging.INFO)

# Set up Web3 and Infura API
INFURA_URL = f"https://mainnet.infura.io/v3/{INFURA_API_KEY}"
w3 = Web3(HTTPProvider(INFURA_URL))

# last_block_number = w3.eth.block_number - 5

last_block_number = w3.eth.block_number -1
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
    global last_block_number
    res = []

    event_signature_hash = w3.keccak(text="Transfer(address,address,uint256)").hex()
    from_block = last_block_number

    filter_params = {
        "fromBlock": from_block,
        "toBlock": "latest",
        "topics": [event_signature_hash]
    }

    logs = w3.eth.get_logs(filter_params)

    for log in logs:
        if len(log['topics']) == 3:
            topics = log['topics']
            sender = '0x' + topics[1].hex()[-40:]
            recipient = '0x' + topics[2].hex()[-40:]
            if sender == address.lower() or recipient == address.lower():
                res.append(log)

    print(res)
    last_block_number = w3.eth.block_number
    return res

# Function to get ETH transactions for a given wallet address
async def get_eth_transactions(address):
    global last_block_number

    from_block = last_block_number
    api_endpoint = f"https://api.etherscan.io/api?module=account&action=txlist&address={address}&startblock={from_block}&endblock=latest&page=1&offset=10&sort=desc&apikey={ETHERSCAN_API_KEY}"

    response = requests.get(api_endpoint)
    transactions = response.json()["result"]

    relevant_transactions = [tx for tx in transactions if tx["to"].lower() == address.lower() or tx["from"].lower() == address.lower()]

    last_block_number = w3.eth.block_number

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

    erc20_abi = []
    with open("./erc20_abi.json") as f:
        erc20_abi = json.load(f)
    while True:
        for address in addresses:
            transactions = await get_erc20_transactions(address)
            eth_transactions = await get_eth_transactions(address)

            nickname = ""  # Initialize nickname variable
            action = ""  # Initialize action variable

            # Handle erc20 transactions
            for tx in transactions:
                value = int(tx['data'].hex(), 16)

                contractAddress = str(tx['address'])
                contract = w3.eth.contract(address=contractAddress, abi=erc20_abi)

                token_symbol = contract.functions.symbol().call()
                token_decimal = contract.functions.decimals().call()

                topics = tx['topics']
                sender = '0x' + topics[1].hex()[-40:]
                recipient = '0x' + topics[2].hex()[-40:]

                transfer_amount = value / (10 ** token_decimal)
                message = ''
                if sender == address.lower():
                    action = "sent"
                    nickname = address_nicknames[address]

                    message = f"{nickname} ({sender}) {action} {transfer_amount} {token_symbol} to {recipient}"
                elif recipient == address.lower():
                    action = "received"
                    nickname = address_nicknames[address]

                    message = f"{nickname} ({recipient}) {action} {transfer_amount} {token_symbol} from {sender}"

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