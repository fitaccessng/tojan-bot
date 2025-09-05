import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters
import httpx
import os
from web3 import Web3

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("BOT_TOKEN environment variable not set!")
    exit(1)

# Define states for the conversation
ASK_WALLET_DETAILS = 1
ASK_TOKEN = 2
ASK_COPY_TRADE = 3
ASK_BUY_SLIPPAGE = 4
ASK_SELL_SLIPPAGE = 5
ASK_SNIPER_ACTION = 6
ASK_LIMIT_ORDER_DETAILS = 7
ASK_WALLET_LABEL = 8
ASK_CHAIN_SELECTION = 9

# Supported chains
SUPPORTED_CHAINS = {
    "ethereum": {"name": "Ethereum", "symbol": "ETH", "explorer": "https://etherscan.io"},
    "solana": {"name": "Solana", "symbol": "SOL", "explorer": "https://solscan.io"},
    "bsc": {"name": "Binance Smart Chain", "symbol": "BNB", "explorer": "https://bscscan.com"},
    "arbitrum": {"name": "Arbitrum", "symbol": "ETH", "explorer": "https://arbiscan.io"},
    "polygon": {"name": "Polygon", "symbol": "MATIC", "explorer": "https://polygonscan.com"}
}

referrals = {}  # user_id -> referrer_id
referral_stats = {}  # referrer_id -> set of referred user_ids

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    balance_eth = 0
    balance_usd = 0

    # Check for referral code in /start <referral_code>
    referrer_id = None
    if context.args:
        try:
            referrer_id = int(context.args[0])
            if referrer_id != user_id and user_id not in referrals:
                referrals[user_id] = referrer_id
                referral_stats.setdefault(referrer_id, set()).add(user_id)
        except Exception:
            pass  # Ignore invalid referral codes

    text = (
        f"🔮 Welcome to Mystro - Your Multi-Chain Trading Assistant\n\n"
        f"💼 Supported Chains: Ethereum, Solana, BSC, Arbitrum, Polygon\n"
        f"💸 Supported Tokens: ETH, SOL, BNB, USDT, USDC, and popular meme coins\n\n"
        f"Click on the Refresh button to update your current balance.\n\n"
        f"Join our [Telegram group](https://t.me/mystrobot) and follow us on [Twitter](https://twitter.com/MystroBot)!\n\n"
        f"⚠ We have no control over Telegram ads in this bot. If the menu disappears, type /start or /help to bring it back. Please be cautious of fake airdrops and login pages."
    )

    keyboard = [
        [InlineKeyboardButton("Buy", callback_data="buy"), InlineKeyboardButton("Sell", callback_data="sell")],
        [InlineKeyboardButton("Positions", callback_data="positions"), InlineKeyboardButton("Wallet", callback_data="wallet")],
        [InlineKeyboardButton("DCA Orders", callback_data="dca_orders"), InlineKeyboardButton("Copy Trade", callback_data="copy_trade")],
        [InlineKeyboardButton("Sniper 🆕", callback_data="sniper"), InlineKeyboardButton("Limit Orders", callback_data="limit_orders"), InlineKeyboardButton("⭐ Watchlist", callback_data="watchlist")],
        [InlineKeyboardButton("Multi-Chain", callback_data="multichain"), InlineKeyboardButton("💰 Referrals", callback_data="referrals")],
        [InlineKeyboardButton("Withdraw", callback_data="withdraw"), InlineKeyboardButton("Settings", callback_data="settings")],
        [InlineKeyboardButton("Help", callback_data="help"), InlineKeyboardButton("🔄 Refresh", callback_data="refresh")]
    ]

    if update.message:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
            disable_web_page_preview=True
        )

async def ask_wallet_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask the user for their wallet details."""
    await update.callback_query.answer()
    
    # First ask which chain they want to import for
    keyboard = [
        [InlineKeyboardButton("Ethereum", callback_data="import_ethereum")],
        [InlineKeyboardButton("Solana", callback_data="import_solana")],
        [InlineKeyboardButton("BSC", callback_data="import_bsc")],
        [InlineKeyboardButton("Arbitrum", callback_data="import_arbitrum")],
        [InlineKeyboardButton("Polygon", callback_data="import_polygon")],
        [InlineKeyboardButton("Cancel", callback_data="cancel_import")]
    ]
    
    await update.callback_query.message.reply_text(
        "Select the blockchain network for your wallet:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return ASK_CHAIN_SELECTION

async def handle_chain_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the chain selection for wallet import."""
    query = update.callback_query
    await query.answer()
    
    action = query.data
    if action.startswith("import_"):
        chain = action.replace("import_", "")
        context.user_data["import_chain"] = chain
        chain_info = SUPPORTED_CHAINS.get(chain, {})
        
        keyboard = [
            [InlineKeyboardButton("Proceed With Import", callback_data="proceed_import"), 
             InlineKeyboardButton("Cancel", callback_data="cancel_import")]
        ]
        
        await query.edit_message_text(
            f"Importing {chain_info.get('name', chain)} wallet\n\n"
            "Accepted formats:\n"
            "- Ethereum/BSC/Arbitrum/Polygon: Private key (64 chars) or seed phrase\n"
            "- Solana: Private key (64-88 chars) or seed phrase\n\n"
            "⚠️ Never share your private keys with anyone!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return ASK_WALLET_DETAILS
    else:
        await query.edit_message_text("Wallet import canceled.")
        return ConversationHandler.END

async def proceed_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask the user to enter their wallet details after clicking 'Proceed'."""
    await update.callback_query.answer()
    chain = context.user_data.get("import_chain", "ethereum")
    chain_info = SUPPORTED_CHAINS.get(chain, {})
    
    await update.callback_query.message.reply_text(
        f"Please provide your {chain_info.get('name', chain)} wallet private key or seed phrase:",
        parse_mode="Markdown"
    )
    return ASK_WALLET_DETAILS

async def save_wallet_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save the user's private key and display confirmation options."""
    wallet_data = update.message.text.strip()
    chain = context.user_data.get("import_chain", "ethereum")
    chain_info = SUPPORTED_CHAINS.get(chain, {})
    
    # Basic validation based on chain
    if chain == "solana":
        if not (64 <= len(wallet_data) <= 88):
            await update.message.reply_text(
                f"❌ Invalid {chain_info.get('name', chain)} private key.\n\n"
                "Solana private keys should be 64-88 characters long.\n"
                "Try again with the correct format.",
                parse_mode="Markdown"
            )
            return ASK_WALLET_DETAILS
    else:  # EVM chains
        if not (len(wallet_data) == 64 or len(wallet_data.split()) >= 12):
            await update.message.reply_text(
                f"❌ Invalid {chain_info.get('name', chain)} private key/seed phrase.\n\n"
                "EVM private keys should be 64 characters long or a valid seed phrase (12+ words).\n"
                "Try again with the correct format.",
                parse_mode="Markdown"
            )
            return ASK_WALLET_DETAILS

    # Save the wallet data
    context.user_data["wallet_data"] = wallet_data
    logger.info(f"{chain_info.get('name', chain)} wallet data entered: {wallet_data[:10]}...")  # Log partial data for security
    
    # Generate address if possible
    address = "Unable to generate"
    if chain != "solana" and len(wallet_data) == 64:
        try:
            w3 = Web3()
            acct = w3.eth.account.from_key(wallet_data)
            address = acct.address
        except Exception as e:
            logger.error(f"Error generating EVM address: {e}")
    
    # Display confirmation message with buttons
    keyboard = [
        [InlineKeyboardButton("Finalize Import", callback_data="finalize_import"), 
         InlineKeyboardButton("Cancel", callback_data="cancel_import")]
    ]
    
    await update.message.reply_text(
        f"🔐 {chain_info.get('name', chain)} Wallet to be imported\n\n"
        f"Address: {address}\n"
        f"Explorer: {chain_info.get('explorer', '')}\n\n"
        "Please confirm the import:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

async def finalize_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finalize the wallet import process."""
    await update.callback_query.answer()
    wallet_data = context.user_data.get("wallet_data", None)
    chain = context.user_data.get("import_chain", "ethereum")
    chain_info = SUPPORTED_CHAINS.get(chain, {})

    if not wallet_data:
        await update.callback_query.message.reply_text(
            "❌ No wallet data found.\n\nPlease restart the import process.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    # Confirm the wallet import
    await update.callback_query.message.reply_text(
        f"✅ {chain_info.get('name', chain)} wallet imported successfully!\n\n"
        "You can now use this wallet for trading.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the wallet import process."""
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("❌ Wallet import canceled.")
    return ConversationHandler.END

async def ask_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask the user to input a token symbol or address."""
    await update.callback_query.answer()
    
    # First ask which chain they want to trade on
    keyboard = [
        [InlineKeyboardButton("Ethereum", callback_data="trade_ethereum")],
        [InlineKeyboardButton("Solana", callback_data="trade_solana")],
        [InlineKeyboardButton("BSC", callback_data="trade_bsc")],
        [InlineKeyboardButton("Arbitrum", callback_data="trade_arbitrum")],
        [InlineKeyboardButton("Polygon", callback_data="trade_polygon")],
        [InlineKeyboardButton("Cancel", callback_data="cancel_trade")]
    ]
    
    await update.callback_query.message.reply_text(
        "Select the blockchain network for your trade:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return ASK_CHAIN_SELECTION

async def handle_trade_chain_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the chain selection for trading."""
    query = update.callback_query
    await query.answer()
    
    action = query.data
    if action.startswith("trade_"):
        chain = action.replace("trade_", "")
        context.user_data["trade_chain"] = chain
        chain_info = SUPPORTED_CHAINS.get(chain, {})
        
        await query.edit_message_text(
            f"Enter a token symbol or address to buy on {chain_info.get('name', chain)}:",
            parse_mode="Markdown"
        )
        return ASK_TOKEN
    else:
        await query.edit_message_text("Trade canceled.")
        return ConversationHandler.END

async def process_token(update: Update, context: ContextTypes.DEFAULT_TYPE, token_query=None):
    """Process the token symbol or address provided by the user."""
    if not token_query:
        token_query = update.message.text.strip()
    
    chain = context.user_data.get("trade_chain", "ethereum")
    chain_info = SUPPORTED_CHAINS.get(chain, {})
    
    await update.message.reply_text(
        f"🔍 Searching for token on {chain_info.get('name', chain)}: {token_query}...",
        parse_mode="Markdown"
    )

    # Different API endpoints for different chains
    if chain == "solana":
        url = f"https://api.dexscreener.com/latest/dex/search?q={token_query}"
    else:  # EVM chains
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_query}"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)

        if response.status_code != 200:
            logger.error(f"Dexscreener API request failed with status code {response.status_code}")
            await update.message.reply_text(
                "❌ Failed to fetch token information. Please try again later.",
                parse_mode="Markdown"
            )
            return ConversationHandler.END

        data = response.json()
        logger.info(f"Dexscreener API response received for token: {token_query}")

        # Check if token data is available
        if not data.get("pairs"):
            await update.message.reply_text(
                f"❌ No data found for token: {token_query} on {chain_info.get('name', chain)}.",
                parse_mode="Markdown"
            )
            return ConversationHandler.END

        # Extract relevant information from the first pair
        pair = data["pairs"][0]
        token_name = pair.get("baseToken", {}).get("name", "Unknown")
        token_symbol = pair.get("baseToken", {}).get("symbol", "Unknown")
        price_usd = pair.get("priceUsd", "N/A")
        liquidity_usd = pair.get("liquidity", {}).get("usd", "N/A")
        volume_usd = pair.get("volume", {}).get("usd24h", "N/A")
        dex_name = pair.get("dexId", "Unknown")
        chain_name = pair.get("chainId", chain_info.get('name', chain))

        # Send token information to the user
        await update.message.reply_text(
            f"💰 Token Information ({chain_name})\n\n"
            f"🔹 Name: {token_name}\n"
            f"🔹 Symbol: {token_symbol}\n"
            f"🔹 Price (USD): ${price_usd}\n"
            f"🔹 Liquidity (USD): ${liquidity_usd}\n"
            f"🔹 24h Volume (USD): ${volume_usd}\n"
            f"🔹 DEX: {dex_name}\n\n"
            f"Use this information to make informed decisions.\n\n"
            f"📌 Note: Always verify token details and trade responsibly.",
            parse_mode="Markdown"
        )

        # Add buttons for amounts based on chain
        chain_symbol = chain_info.get('symbol', 'ETH')
        keyboard = [
            [InlineKeyboardButton(f"0.5 {chain_symbol}", callback_data=f"buy_0.5_{chain}"), 
             InlineKeyboardButton(f"1 {chain_symbol}", callback_data=f"buy_1_{chain}")],
            [InlineKeyboardButton(f"3 {chain_symbol}", callback_data=f"buy_3_{chain}"), 
             InlineKeyboardButton(f"5 {chain_symbol}", callback_data=f"buy_5_{chain}")],
            [InlineKeyboardButton(f"10 {chain_symbol}", callback_data=f"buy_10_{chain}"), 
             InlineKeyboardButton(f"20 {chain_symbol}", callback_data=f"buy_20_{chain}")],
            [InlineKeyboardButton(f"30 {chain_symbol}", callback_data=f"buy_30_{chain}"), 
             InlineKeyboardButton(f"X {chain_symbol}", callback_data=f"buy_X_{chain}")],
            [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"Select the amount of {chain_symbol} you want to use for this token:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error while querying Dexscreener API: {e}")
        await update.message.reply_text(
            "❌ An error occurred while fetching token information. Please try again later.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /buy command."""
    if len(context.args) == 0:
        await update.message.reply_text(
            "💰 Buy Menu\n\n"
            "Enter a token symbol or address to buy. Example:\n"
            "/buy ETH or /buy 0x123...\n\n"
            "You can also specify the chain:\n"
            "/buy ETH ethereum\n"
            "/buy SOL solana\n"
            "/buy USDC arbitrum",
            parse_mode="Markdown"
        )
        return

    token_query = context.args[0].strip()
    chain = "ethereum"  # default
    
    if len(context.args) > 1:
        chain = context.args[1].strip().lower()
        if chain not in SUPPORTED_CHAINS:
            await update.message.reply_text(
                f"❌ Unsupported chain: {chain}\n\n"
                f"Supported chains: {', '.join(SUPPORTED_CHAINS.keys())}",
                parse_mode="Markdown"
            )
            return
    
    context.user_data["trade_chain"] = chain
    await process_token(update, context, token_query)

async def sell_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /sell command."""
    await update.message.reply_text(
        "❌ You do not have any tokens to sell at the moment.",
        parse_mode="Markdown"
    )

async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /positions command."""
    keyboard = [
        [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📊 You currently have no open positions.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /settings command."""
    keyboard = [
        [InlineKeyboardButton("Buy Settings", callback_data="buy_settings"), InlineKeyboardButton("Sell Settings", callback_data="sell_settings")],
        [InlineKeyboardButton("Set Referral", callback_data="set_referral"), InlineKeyboardButton("Confirm Trades", callback_data="confirm_trades")],
        [InlineKeyboardButton("Chain Settings", callback_data="chain_settings")],
        [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "⚙ Settings Menu\n\n"
        "Select an option below:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def snipe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /snipe command."""
    keyboard = [
        [InlineKeyboardButton("Wallet", callback_data="wallet")],
        [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "❌ Insufficient balance to snipe.\n\n"
        "Please make a deposit to proceed.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def burn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /burn command."""
    keyboard = [
        [InlineKeyboardButton("Wallet", callback_data="wallet")],
        [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "❌ No token to burn.\n\n"
        "Deposit tokens to proceed.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /withdraw command."""
    keyboard = [
        [InlineKeyboardButton("Wallet", callback_data="wallet")],
        [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "❌ Zero balance.\n\n"
        "Please deposit funds to proceed.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /backup command."""
    await update.message.reply_text(
        "🔐 Backup Your Wallet\n\n"
        "Please select which wallet you'd like to back up:",
        parse_mode="Markdown"
    )
    
    # Show list of wallets to backup
    keyboard = [
        [InlineKeyboardButton("Ethereum Wallet", callback_data="backup_ethereum")],
        [InlineKeyboardButton("Solana Wallet", callback_data="backup_solana")],
        [InlineKeyboardButton("BSC Wallet", callback_data="backup_bsc")],
        [InlineKeyboardButton("Cancel", callback_data="cancel_backup")]
    ]
    
    await update.message.reply_text(
        "Select wallet to backup:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return ASK_WALLET_DETAILS

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /help command."""
    help_text = (
        "📖 How do I use Mystro?\n"
        "Mystro is a multi-chain trading bot supporting Ethereum, Solana, BSC, Arbitrum and Polygon.\n\n"
        "🔹 /buy - Buy tokens on any supported chain\n"
        "🔹 /sell - Sell your tokens\n"
        "🔹 /wallet - Manage your wallets\n"
        "🔹 /positions - View your open positions\n\n"
        "📌 Where can I find my referral code?\n"
        "Open the /start menu and click 💰Referrals.\n\n"
        "💰 What are the fees for using Mystro?\n"
        "Successful transactions through Mystro incur a small fee (0.5-1%). We don't charge a subscription fee.\n\n"
        "🔒 Security Tips:\n"
        " - NEVER share your private keys with anyone!\n"
        " - Mystro will NEVER ask for your seed phrase\n"
        " - Always verify token contracts before trading\n\n"
        "❓ Need support? Join our Telegram group @mystrobot"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown", disable_web_page_preview=True)

async def cancel_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the buy process."""
    await update.message.reply_text("❌ Buy process canceled.")
    return ConversationHandler.END

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data
    logger.info(f"User {query.from_user.id} clicked: {action}")

    if action == "import_wallet":
        await ask_wallet_details(update, context)
        return

    if action == "multichain":
        try:
            message = "🌐 Multi-Chain Support\n\n"
            for chain, info in SUPPORTED_CHAINS.items():
                message += f"🔹 {info['name']} ({info['symbol']})\n"
            
            message += "\nSelect a chain to view more options:"
            
            keyboard = [
                [InlineKeyboardButton("Ethereum", callback_data="chain_ethereum")],
                [InlineKeyboardButton("Solana", callback_data="chain_solana")],
                [InlineKeyboardButton("BSC", callback_data="chain_bsc")],
                [InlineKeyboardButton("Arbitrum", callback_data="chain_arbitrum")],
                [InlineKeyboardButton("Polygon", callback_data="chain_polygon")],
                [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
            ]
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return
        except Exception as e:
            logger.error(f"Error showing multichain info: {e}")
            await query.edit_message_text(
                "❌ Error loading chain information",
                parse_mode="Markdown"
            )

    # Handle chain-specific actions
    if action.startswith("chain_"):
        chain = action.replace("chain_", "")
        chain_info = SUPPORTED_CHAINS.get(chain, {})
        
        keyboard = [
            [InlineKeyboardButton(f"Buy on {chain_info.get('name', chain)}", callback_data=f"trade_{chain}")],
            [InlineKeyboardButton(f"Import {chain_info.get('name', chain)} Wallet", callback_data=f"import_{chain}")],
            [InlineKeyboardButton(f"View {chain_info.get('name', chain)} Stats", callback_data=f"stats_{chain}")],
            [InlineKeyboardButton("⬅ Back", callback_data="multichain")]
        ]
        
        await query.edit_message_text(
            f"🔗 {chain_info.get('name', chain)} Options\n\n"
            f"Symbol: {chain_info.get('symbol', '')}\n"
            f"Explorer: {chain_info.get('explorer', '')}\n\n"
            "Select an option:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return

    # Handle other button actions...
    elif action == "buy":
        await ask_token(update, context)
    elif action.startswith("buy_"):
        parts = action.split("_")
        amount = parts[1]
        chain = parts[2] if len(parts) > 2 else "ethereum"
        chain_info = SUPPORTED_CHAINS.get(chain, {})
        
        keyboard = [
            [InlineKeyboardButton("Wallet", callback_data="wallet")],
            [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
        ]
        await query.edit_message_text(
            f"❌ Insufficient {chain_info.get('symbol', 'ETH')} balance to complete the purchase.\n\n"
            "Please make a deposit to proceed.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    elif action == "wallet":
        # Show all imported wallets
        wallet_keyboard = [
            [InlineKeyboardButton("Import Ethereum Wallet", callback_data="import_ethereum"), 
             InlineKeyboardButton("Import Solana Wallet", callback_data="import_solana")],
            [InlineKeyboardButton("Import BSC Wallet", callback_data="import_bsc"), 
             InlineKeyboardButton("Import Arbitrum Wallet", callback_data="import_arbitrum")],
            [InlineKeyboardButton("Import Polygon Wallet", callback_data="import_polygon")],
            [InlineKeyboardButton("Backup Wallet", callback_data="backup_wallet")],
            [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
        ]
        
        wallet_message = (
            "🔐 Wallet Management\n\n"
            "Supported wallets:\n"
            "🔹 Ethereum: 0x5FA5... (0.5 ETH)\n"
            "🔹 Solana: 6dyzT... (0 SOL)\n"
            "🔹 BSC: 0x3F2A... (10 BNB)\n\n"
            "Select an option:"
        )
        
        await query.edit_message_text(
            wallet_message,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(wallet_keyboard)
        )
    elif action == "positions":
        keyboard = [[InlineKeyboardButton("⬅ Back", callback_data="main_menu")]]
        await query.edit_message_text(
            "📊 You currently have no open positions.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    elif action == "sell":
        keyboard = [[InlineKeyboardButton("⬅ Back", callback_data="main_menu")]]
        await query.edit_message_text(
            "❌ You do not have any tokens to sell at the moment.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    elif action == "main_menu":
        keyboard = [
            [InlineKeyboardButton("Buy", callback_data="buy"), InlineKeyboardButton("Sell", callback_data="sell")],
            [InlineKeyboardButton("Positions", callback_data="positions"), InlineKeyboardButton("Wallet", callback_data="wallet")],
            [InlineKeyboardButton("DCA Orders", callback_data="dca_orders"), InlineKeyboardButton("Copy Trade", callback_data="copy_trade")],
            [InlineKeyboardButton("Sniper 🆕", callback_data="sniper"), InlineKeyboardButton("Limit Orders", callback_data="limit_orders"), InlineKeyboardButton("⭐ Watchlist", callback_data="watchlist")],
            [InlineKeyboardButton("Multi-Chain", callback_data="multichain"), InlineKeyboardButton("💰 Referrals", callback_data="referrals")],
            [InlineKeyboardButton("Withdraw", callback_data="withdraw"), InlineKeyboardButton("Settings", callback_data="settings")],
            [InlineKeyboardButton("Help", callback_data="help"), InlineKeyboardButton("🔄 Refresh", callback_data="refresh")]
        ]
        await query.edit_message_text(
            "Welcome back to the main menu! Select an option below:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    elif action == "buy_settings":
        await query.edit_message_text(
            "⚙ Buy Settings\n\n"
            "Please input the slippage percentage for buying (e.g., 0.5 for 0.5%):",
            parse_mode="Markdown"
        )
        return ASK_BUY_SLIPPAGE
    elif action == "sell_settings":
        await query.edit_message_text(
            "⚙ Sell Settings\n\n"
            "Please input the slippage percentage for selling (e.g., 0.5 for 0.5%):",
            parse_mode="Markdown"
        )
        return ASK_SELL_SLIPPAGE
    elif action == "settings":
        keyboard = [
            [InlineKeyboardButton("Buy Settings", callback_data="buy_settings"), InlineKeyboardButton("Sell Settings", callback_data="sell_settings")],
            [InlineKeyboardButton("Set Referral", callback_data="set_referral"), InlineKeyboardButton("Confirm Trades", callback_data="confirm_trades")],
            [InlineKeyboardButton("Chain Settings", callback_data="chain_settings")],
            [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
        ]
        await query.edit_message_text(
            "⚙ Settings Menu\n\n"
            "Select an option below:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    elif action == "dca_orders":
        keyboard = [[InlineKeyboardButton("⬅ Back", callback_data="main_menu")]]
        await query.edit_message_text(
            "📊 DCA Orders\n\n"
            "You currently have no active DCA orders.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    elif action == "copy_trade":
        await query.edit_message_text(
            "Please provide the address you'd like to copy trades from:",
            parse_mode="Markdown"
        )
        return ASK_COPY_TRADE
    elif action == "sniper":
        await query.edit_message_text(
            "Please provide the token address or action you'd like to snipe:",
            parse_mode="Markdown"
        )
        return ASK_SNIPER_ACTION
    elif action == "limit_orders":
        keyboard = [
            [InlineKeyboardButton("Create Limit Order", callback_data="create_limit_order")],
            [InlineKeyboardButton("View Active Orders", callback_data="view_active_orders")],
            [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
        ]
        await query.edit_message_text(
            "📈 Limit Orders Menu\n\n"
            "Select an option below:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    elif action == "create_limit_order":
        await query.edit_message_text(
            "📝 Create Limit Order\n\n"
            "Please provide the token symbol, price, and amount for the limit order in the following format:\n"
            "<TOKEN_SYMBOL> <PRICE> <AMOUNT>\n\n"
            "Example: ETH 2000 0.5 (to buy 0.5 ETH at $2000 each).",
            parse_mode="Markdown"
        )
        return ASK_LIMIT_ORDER_DETAILS
    elif action == "view_active_orders":
        active_orders = context.user_data.get("active_orders", [])
        if not active_orders:
            await query.edit_message_text(
                "📋 Active Limit Orders\n\n"
                "You currently have no active limit orders.",
                parse_mode="Markdown"
            )
        else:
            orders_text = "\n".join([f"🔹 {order}" for order in active_orders])
            await query.edit_message_text(
                f"📋 Active Limit Orders\n\n{orders_text}",
                parse_mode="Markdown"
            )
    elif action == "label_wallet":
        await query.edit_message_text(
            "📝 Label Wallet\n\n"
            "Please provide a label for your wallet (e.g., 'Main Wallet', 'Savings Wallet').",
            parse_mode="Markdown"
        )
        return ASK_WALLET_LABEL
    elif action == "delete_wallet":
        await query.edit_message_text(
            "❌ Delete Wallet\n\n"
            "This feature is currently closed.",
            parse_mode="Markdown"
        )
    elif action == "refresh_wallet":
        await query.edit_message_text(
            "🔄 Refresh Wallet\n\n"
            "Refreshed.",
            parse_mode="Markdown"
        )
    elif action == "withdraw":
        keyboard = [
            [InlineKeyboardButton("Wallet", callback_data="wallet")],
            [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
        ]
        await query.edit_message_text(
            "❌ Zero balance.\n\n"
            "Please deposit funds to proceed.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    elif action == "help":
        help_text = (
            "📖 Mystro Help\n\n"
            "Mystro is a multi-chain trading bot supporting:\n"
            "🔹 Ethereum (ETH, USDT, USDC, meme coins)\n"
            "🔹 Solana (SOL, USDC, meme coins)\n"
            "🔹 Binance Smart Chain (BNB, BUSD, meme coins)\n"
            "🔹 Arbitrum (ETH, USDC)\n"
            "🔹 Polygon (MATIC, USDC)\n\n"
            "Basic Commands:\n"
            "/buy - Buy tokens on any chain\n"
            "/sell - Sell your tokens\n"
            "/wallet - Manage your wallets\n"
            "/positions - View open positions\n\n"
            "For more help, join @mystrobot"
        )
        await query.edit_message_text(
            help_text,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    elif action == "refresh":
        await query.edit_message_text(
            "🔄 Your balance and data have been refreshed.",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text("❌ Invalid action. Please try again.", parse_mode="Markdown")

async def handle_copy_trade_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the address provided for copy trade."""
    address = update.message.text.strip()
    context.user_data["copy_trade_address"] = address
    logger.info(f"Copy trade address entered: {address}")
    await update.message.reply_text(
        f"✅ Connected successfully to address: {address}\n\n"
        "You are now copying trades from this user.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def handle_buy_slippage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the slippage input for Buy Settings."""
    slippage = update.message.text.strip()
    if not slippage.replace('.', '', 1).isdigit():
        await update.message.reply_text(
            "❌ Invalid input.\n\n"
            "Please provide a valid slippage percentage (e.g., 0.5 for 0.5%).",
            parse_mode="Markdown"
        )
        return ASK_BUY_SLIPPAGE

    context.user_data["buy_slippage"] = slippage
    await update.message.reply_text(
        f"✅ Buy slippage recorded: {slippage}%\n\n"
        "Slippage has been set successfully.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def handle_sell_slippage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the slippage input for Sell Settings."""
    slippage = update.message.text.strip()
    if not slippage.replace('.', '', 1).isdigit():
        await update.message.reply_text(
            "❌ Invalid input.\n\n"
            "Please provide a valid slippage percentage (e.g., 0.5 for 0.5%).",
            parse_mode="Markdown"
        )
        return ASK_SELL_SLIPPAGE

    context.user_data["sell_slippage"] = slippage
    await update.message.reply_text(
        f"✅ Sell slippage recorded: {slippage}%\n\n"
        "Slippage has been set successfully.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def handle_sniper_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the sniper action."""
    sniper_input = update.message.text.strip()
    if not sniper_input:
        await update.message.reply_text(
            "❌ Invalid input.\n\n"
            "Please provide a valid sniper action or token address.",
            parse_mode="Markdown"
        )
        return ASK_SNIPER_ACTION

    context.user_data["sniper_action"] = sniper_input
    await update.message.reply_text(
        f"✅ Sniper action recorded: {sniper_input}\n\n"
        "You can now proceed with your sniper action.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def handle_limit_order_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the details for creating a limit order."""
    order_details = update.message.text.strip()
    try:
        token_symbol, price, amount = order_details.split()
        price = float(price)
        amount = float(amount)

        order = f"{amount} {token_symbol} at ${price}"
        if "active_orders" not in context.user_data:
            context.user_data["active_orders"] = []
        context.user_data["active_orders"].append(order)

        await update.message.reply_text(
            f"✅ Limit Order Created:\n\n"
            f"🔹 {amount} {token_symbol} at ${price}\n\n"
            "You can view your active orders in the Limit Orders menu.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid input format.\n\n"
            "Please provide the token symbol, price, and amount in the following format:\n"
            "<TOKEN_SYMBOL> <PRICE> <AMOUNT>\n\n"
            "Example: ETH 2000 0.5 (to buy 0.5 ETH at $2000 each).",
            parse_mode="Markdown"
        )
        return ASK_LIMIT_ORDER_DETAILS

async def handle_wallet_label(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the wallet label input."""
    label = update.message.text.strip()
    if not label:
        await update.message.reply_text(
            "❌ Invalid label.\n\n"
            "Please provide a valid label for your wallet.",
            parse_mode="Markdown"
        )
        return ASK_WALLET_LABEL

    context.user_data["wallet_label"] = label
    logger.info(f"Wallet label entered: {label}")
    await update.message.reply_text(
        f"✅ Wallet labeled as: {label}\n\n"
        "You can now use this label to identify your wallet.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("backup", backup_command),
            CommandHandler("buy", buy_command),
            CallbackQueryHandler(ask_wallet_details, pattern="^import_wallet$"),
            CallbackQueryHandler(proceed_import, pattern="^proceed_import$"),
            CallbackQueryHandler(ask_token, pattern="^buy$"),
            CallbackQueryHandler(button_handler, pattern="^trade_.*$"),
            CallbackQueryHandler(button_handler, pattern="^copy_trade$"),
            CallbackQueryHandler(button_handler, pattern="^sell$"),
            CallbackQueryHandler(button_handler, pattern="^limit_orders$"),
            CallbackQueryHandler(button_handler, pattern="^create_limit_order$"),
            CallbackQueryHandler(button_handler, pattern="^view_active_orders$"),
            CallbackQueryHandler(button_handler, pattern="^sniper$"),
            CallbackQueryHandler(button_handler, pattern="^multichain$"),
            CallbackQueryHandler(button_handler, pattern="^referrals$"),
            CallbackQueryHandler(button_handler, pattern="^label_wallet$"),
        ],
        states={
            ASK_CHAIN_SELECTION: [
                CallbackQueryHandler(handle_chain_selection, pattern="^import_.*$"),
                CallbackQueryHandler(handle_trade_chain_selection, pattern="^trade_.*$")
            ],
            ASK_WALLET_DETAILS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_wallet_details)
            ],
            ASK_TOKEN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_token),
            ],
            ASK_COPY_TRADE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_copy_trade_address)
            ],
            ASK_BUY_SLIPPAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buy_slippage)
            ],
            ASK_SELL_SLIPPAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sell_slippage)
            ],
            ASK_LIMIT_ORDER_DETAILS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_limit_order_details)
            ],
            ASK_WALLET_LABEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_wallet_label)
            ],
            ASK_SNIPER_ACTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sniper_action)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_import),
            CommandHandler("cancel", cancel_buy),
            CallbackQueryHandler(cancel_import, pattern="^cancel_import$"),
            CallbackQueryHandler(finalize_import, pattern="^finalize_import$"),
            CallbackQueryHandler(cancel_import, pattern="^cancel_backup$"),
            CallbackQueryHandler(cancel_import, pattern="^cancel_trade$"),
        ],
    )

    # Add all handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CommandHandler("sell", sell_command))
    app.add_handler(CommandHandler("positions", positions_command))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CommandHandler("snipe", snipe_command))
    app.add_handler(CommandHandler("burn", burn_command))
    app.add_handler(CommandHandler("withdraw", withdraw_command))
    app.add_handler(CommandHandler("backup", backup_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(proceed_import, pattern="^proceed_import$"))
    app.add_handler(CallbackQueryHandler(finalize_import, pattern="^finalize_import$"))
    app.add_handler(CallbackQueryHandler(cancel_import, pattern="^cancel_import$"))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Mystro bot starting...")
    app.run_polling()