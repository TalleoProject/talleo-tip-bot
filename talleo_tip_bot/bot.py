import asyncio
import click
import discord
import mongoengine
from discord.ext import commands

from mongoengine.errors import ValidationError

from talleo_tip_bot import models, store
from talleo_tip_bot.config import config

TALLEO_DIGITS = 100
TALLEO_REPR = 'TLO'

bot_description = f"Tip {TALLEO_REPR} to other users on your server."
bot_help_register = "Register or change your withdrawal address."
bot_help_info = "Get your account's info."
bot_help_withdraw = f"Withdraw {TALLEO_REPR} from your balance."
bot_help_balance = f"Check your {TALLEO_REPR} balance."
bot_help_transfer = f"Send {TALLEO_REPR} to external wallet from your balance."
bot_help_tip = f"Give {TALLEO_REPR} to a user from your balance."
bot_help_optimize = "Optimize wallet."
bot_help_outputs = "Get number of optimizable and unspent outputs."


# Create bot
class TipBot(commands.Bot):

    def __init__(self, *args, **kwargs):
        super(TipBot, self).__init__(*args, **kwargs)

    async def update_balance_wallets(self):
        while not self.is_closed:
            store.update_balances()
            await asyncio.sleep(config.wallet_balance_update_interval)

    # print list of servers where this bot is active to console
    async def list_servers(self):
        await self.tree.sync()
        while not self.is_closed():
            # you can customize the output message(s) below
            print("--- TIP BOT ONLINE ---")
            for guild in self.guilds:
                # you can customize the output message(s) below
                print('Active servers: ' + str(guild.name))
            await asyncio.sleep(600)

intents = discord.Intents.all()
bot = TipBot(command_prefix='$', intents=intents)


@bot.event
async def on_ready():
    print('Ready!')
    print(bot.user.name)
    print(bot.user.id)
    bot.loop.create_task(bot.update_balance_wallets())
    bot.loop.create_task(bot.list_servers())


@bot.hybrid_command(help=bot_help_info)
async def info(context: commands.Context):
    user = store.register_user(str(context.message.author.id))
    await context.reply(f'**Account Info**\n\n'
                        f'Deposit Address: `{user.balance_wallet_address}`\n\n'
                        f'Registered Wallet: `{user.user_wallet_address}`')


@bot.hybrid_command(help=bot_help_balance)
async def balance(context: commands.Context):
    user = store.register_user(str(context.message.author.id))
    wallet = store.get_user_wallet(user.user_id)
    await context.reply(
        '**Your balance**\n\n'
        f'Available: {wallet.actual_balance / TALLEO_DIGITS:.2f} '
        f'{TALLEO_REPR}\n'
        f'Pending: {wallet.locked_balance / TALLEO_DIGITS:.2f} '
        f'{TALLEO_REPR}\n')


@bot.hybrid_command(help=bot_help_register)
async def register(context: commands.Context, wallet_address: str):
    user_id = str(context.message.author.id)

    existing_user: models.User = models.User.objects(user_id=user_id).first()
    if existing_user:
        prev_address = existing_user.user_wallet_address
        existing_user = store.register_user(existing_user.user_id,
                                            user_wallet=wallet_address)
        if prev_address:
            await context.reply(
                f'Your withdrawal address has been changed from:\n'
                f'`{prev_address}`\n to\n '
                f'`{existing_user.user_wallet_address}`')
            return

    user = (existing_user or
            store.register_user(user_id, user_wallet=wallet_address))

    await context.reply(f'You have been registered.\n'
                        f'You can send your deposits to '
                        f'`{user.balance_wallet_address}` and your '
                        f'balance will be available once confirmed.')


@bot.hybrid_command(help=bot_help_withdraw)
async def withdraw(context: commands.Context, amount: float):
    user: models.User = models.User.objects(
        user_id=str(context.message.author.id)).first()
    real_amount = int(amount * TALLEO_DIGITS)

    if not user.user_wallet_address:
        await context.reply('You do not have a withdrawal address, please use '
                            '`$register <wallet_address>` to register.')
        return

    user_balance_wallet: models.Wallet = models.Wallet.objects(
        wallet_address=user.balance_wallet_address).first()

    if real_amount + config.tx_fee >= user_balance_wallet.actual_balance:
        await context.reply(f'Insufficient balance to withdraw '
                            f'{real_amount / TALLEO_DIGITS:.2f} '
                            f'{TALLEO_REPR}.')
        return

    if real_amount > config.max_tx_amount:
        await context.reply(f'Transactions cannot be bigger than '
                            f'{config.max_tx_amount / TALLEO_DIGITS:.2f} '
                            f'{TALLEO_REPR}')
        return
    elif real_amount < config.min_tx_amount:
        await context.reply(f'Transactions cannot be lower than '
                            f'{config.min_tx_amount / TALLEO_DIGITS:.2f} '
                            f'{TALLEO_REPR}')
        return

    withdrawal = store.withdraw(user, real_amount)
    await context.reply(f'You have withdrawn {real_amount / TALLEO_DIGITS:.2f} '
                        f'{TALLEO_REPR}.\n'
                        f'Transaction hash: `{withdrawal.tx_hash}`')


@bot.hybrid_command(help=bot_help_transfer)
async def transfer(context: commands.Context, recipient: str, amount: float):
    user_from: models.User = models.User.objects(
        user_id=str(context.message.author.id)).first()
    user_from_wallet: models.Wallet = models.Wallet.objects(
        wallet_address=user_from.balance_wallet_address).first()
    real_amount = int(amount * TALLEO_DIGITS)

    user_to: models.Wallet = models.Wallet.objects(
        wallet_address=recipient).first()
    if user_to is None:
        try:
            user_to = models.Wallet(wallet_address=recipient)
            user_to.save()
        except ValidationError:
            await context.reply('Invalid wallet address!')
            return

    if real_amount + config.tx_fee >= user_from_wallet.actual_balance:
        await context.reply(f'Insufficient balance to send transfer of '
                            f'{real_amount / TALLEO_DIGITS:.2f} '
                            f'{TALLEO_REPR} to @{recipient}.')
        return

    if real_amount > config.max_tx_amount:
        await context.reply(f'Transactions cannot be bigger than '
                            f'{config.max_tx_amount / TALLEO_DIGITS:.2f} '
                            f'{TALLEO_REPR}.')
        return
    elif real_amount < config.min_tx_amount:
        await context.reply(f'Transactions cannot be smaller than '
                            f'{config.min_tx_amount / TALLEO_DIGITS:.2f} '
                            f'{TALLEO_REPR}.')
        return

    transfer = store.send(user_from, user_to, real_amount)

    await context.reply(f'Transfer of {real_amount / TALLEO_DIGITS:.2f} '
                        f'{TALLEO_REPR} '
                        f'was sent to {recipient}\n'
                        f'Transaction hash: {transfer.tx_hash}')


@bot.hybrid_command(help=bot_help_tip)
async def tip(context: commands.Context, member: discord.Member,
              amount: float):
    user_from: models.User = models.User.objects(
        user_id=str(context.message.author.id)).first()
    user_to: models.User = store.register_user(str(member.id))
    real_amount = int(amount * TALLEO_DIGITS)

    user_from_wallet: models.Wallet = models.Wallet.objects(
        wallet_address=user_from.balance_wallet_address).first()

    if bot.user.mention == member.mention:
        await context.reply('HODL!')
        return

    if context.message.author.mention == member.mention:
        await context.reply('Tipping oneself will just waste your balance!')
        return

    if real_amount + config.tx_fee >= user_from_wallet.actual_balance:
        await context.reply(f'Insufficient balance to send tip of '
                            f'{real_amount / TALLEO_DIGITS:.2f} '
                            f'{TALLEO_REPR} to {member.mention}.')
        return

    if real_amount > config.max_tx_amount:
        await context.reply(f'Transactions cannot be bigger than '
                            f'{config.max_tx_amount / TALLEO_DIGITS:.2f} '
                            f'{TALLEO_REPR}.')
        return
    elif real_amount < config.min_tx_amount:
        await context.reply(f'Transactions cannot be smaller than '
                            f'{config.min_tx_amount / TALLEO_DIGITS:.2f} '
                            f'{TALLEO_REPR}.')
        return

    tip = store.send_tip(user_from, user_to, real_amount)

    await context.reply(f'Tip of {real_amount / TALLEO_DIGITS:.2f} '
                        f'{TALLEO_REPR} '
                        f'was sent to {member.mention}\n'
                        f'Transaction hash: `{tip.tx_hash}`')


@bot.hybrid_command(help=bot_help_outputs)
async def outputs(context: commands.Context):
    user = models.User = models.User.objects(
        user_id=str(context.message.author.id)).first()

    user_balance_wallet: models.Wallet = models.Wallet.objects(
        wallet_address=user.balance_wallet_address).first()

    threshold = user_balance_wallet.actual_balance

    estimate = store.estimate_fusion(user, threshold)

    await context.reply(
        f'Optimizable outputs: `{estimate.fusion_ready_count}`\n'
        f'Unspent outputs: `{estimate.total_count}`')


@bot.hybrid_command(help=bot_help_optimize)
async def optimize(context: commands.Context):
    user = models.User = models.User.objects(
        user_id=str(context.message.author.id)).first()

    user_balance_wallet: models.Wallet = models.Wallet.objects(
        wallet_address=user.balance_wallet_address).first()

    threshold = user_balance_wallet.actual_balance

    estimate = store.estimate_fusion(user, threshold)

    if estimate['fusion_ready_count'] == 0:
        await context.reply('No optimizable outputs!')
        return

    optimize = store.send_fusion(user, threshold)

    await context.reply('Fusion transaction sent.\n'
                        f'Transaction hash: `{optimize.tx_hash}`')


@register.error
async def register_error(context: commands.Context, error):
    await handle_errors(context, error)


@info.error
async def info_error(context: commands.Context, error):
    await handle_errors(context, error)


@balance.error
async def balance_error(context: commands.Context, error):
    await handle_errors(context, error)


@withdraw.error
async def withdraw_error(context: commands.Context, error):
    await handle_errors(context, error)


@transfer.error
async def transfer_error(context: commands.Context, error):
    await handle_errors(context, error)


@tip.error
async def tip_error(context: commands.Context, error):
    await handle_errors(context, error)


@outputs.error
async def outputs_error(context: commands.Context, error):
    await handle_errors(context, error)


@optimize.error
async def optimize_error(context: commands.Context, error):
    await handle_errors(context, error)


async def handle_errors(context: commands.Context, error):
    if isinstance(error, commands.BadArgument):
        await context.reply(f'Invalid arguments provided.\n\n{error.args[0]}')
    else:
        await context.reply(f'Unexpected error.\n\n{error}')


@click.command()
def main():
    mongoengine.connect(db=config.database.db, host=config.database.host,
                        port=config.database.port,
                        username=config.database.user,
                        password=config.database.password)
    bot.run(config.discord.token)


if __name__ == '__main__':
    main()
