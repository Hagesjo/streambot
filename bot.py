from uuid import UUID

import discord
import logging
import requests
import asyncio
import json
from quart import Quart, request

from discord.ext import commands
from discord.utils import get

token = ""
twitch_client_id = ''
twitch_client_secret = ''
twitch_auth_url = f""
app = Quart(__name__)
headers = {"Client-ID": twitch_client_id}

help_text = """
**Commands**:
    `.subscribe <twitchname, e.g glorkwimp>`
    `.unsubscribe <twitchname, e.g glorkwimp>`
    `.subscriptions` - list subscriptions
"""


class Commands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        pass


    @commands.command()
    async def help(self, ctx):
        # should only listen to DM
        if ctx.message.guild is not None:
            return
        await ctx.send(help_text)
    
    @commands.command()
    async def subscriptions(self, ctx, *, query=""):
        # should only listen to DM
        if ctx.message.guild is not None:
            return

        subs = twitch_list_subscriptions()
        users = set()
        for s in subs['data']:
            username = twitch_get_user_name(s['condition']['broadcaster_user_id'])
            users.add(username)
        await ctx.send('Current subscriptions:\n' + '\n'.join(users))

    @commands.command()
    async def subscribe(self, ctx, *, query=""):
        """Subscribe to a channel"""
        # should only listen to DM
        if ctx.message.guild is not None:
            return

        err = twitch_eventsub(query, "stream.online")
        if err:
            await ctx.send(f"could not subscribe: {err}")
            return

        err = twitch_eventsub(query, "stream.offline")
        if err:
            await ctx.send(f"could not subscribe: {err}")
            return

        subs = twitch_list_subscriptions()
        users = set()
        for s in subs['data']:
            username = twitch_get_user_name(s['condition']['broadcaster_user_id'])
            users.add(username)
        await ctx.send('Current subscriptions:\n' + '\n'.join(users))

    @commands.command()
    async def subscribe_follow(self, ctx, *, query=""):
        """Just to test follow"""
        # should only listen to DM
        if ctx.message.guild is not None:
            return

        # guild = get(self.bot.guilds, name="Arcane game")
        err = twitch_eventsub(query, "channel.follow")
        if err:
            await ctx.send(f"could not subscribe: {err}")
            return

        subs = twitch_list_subscriptions()
        users = set()
        for s in subs['data']:
            username = twitch_get_user_name(s['condition']['broadcaster_user_id'])
            users.add(username)
        await ctx.send('Current subscriptions:\n' + '\n'.join(users))

    @commands.command()
    async def unsubscribe(self, ctx, *, query=""):
        err = twitch_unsubscribe(query)
        if err:
            print("could not remove subscription for query", query, err)
            return

        subs = twitch_list_subscriptions()
        users = set()
        for s in subs['data']:
            username = twitch_get_user_name(s['condition']['broadcaster_user_id'])
            users.add(username)
        await ctx.send('Current subscriptions:\n' + '\n'.join(users))


logging.basicConfig(level=logging.INFO)


@app.before_serving
async def before_serving():
    loop = asyncio.get_event_loop()

    bot = commands.Bot(command_prefix=commands.when_mentioned_or("."),
                       description='Stream bot',
                       help_command=None)
    @bot.event
    async def on_ready():
        print('Logged in as {0} ({0.id})'.format(bot.user))
        print('------')
        await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="you"))
        twitch_auth()
    bot.add_cog(Commands(bot))

    app.bot = bot
    await bot.login(token)

    loop.create_task(bot.connect())


@app.route("/webhook", methods=["GET", "POST"])
async def send_message():
    # wait_until_ready and check for valid connection is missing here
    req = json.loads(await request.get_data())
    
    guild = get(app.bot.guilds, name="Pixelbased Lifeforms")
    channel = get(guild.channels, name="livestreams")

    # await channel.send('XYZ')
    if "challenge" in req:
        print("received subscribe:", req)
        return req['challenge'], 200
    else:
        notify_type = req["subscription"]["type"]
        event = req['event']
        if notify_type == "stream.online":
            user = event["broadcaster_user_name"]
            user_url = "https://twitch.tv/"+event["broadcaster_user_login"]
            await channel.send(f"{user} is streaming! Watch him at {user_url}")
        elif notify_type == "stream.offline":
            user = event["broadcaster_user_name"]
            for message in await channel.history().flatten():
                if f"twitch.tv/{user}" in message.content:
                    await message.delete()
        elif notify_type == "channel.follow":
            follower = event['user_login']
            following = event['broadcaster_user_name']
            await channel.send(f"{follower} has followed {following}")

        return "", 200


def twitch_auth():
    r = requests.post(twitch_auth_url)
    if r.status_code != 200:
        print("failed to auth to twitch")
    headers["authorization"] = f"Bearer " + r.json()["access_token"]
    print("Saved auth token from twitch")

def twitch_get_user_id(name):
    r = requests.get(f"https://api.twitch.tv/helix/users?login={name}", headers=headers)
    if r.status_code != 200:
        return "", f"could not get user id: {r.text}"
    return r.json()['data'][0]['id']

def twitch_get_user_name(id):
    r = requests.get(f"https://api.twitch.tv/helix/users?id={id}", headers=headers)
    if r.status_code != 200:
        return "", f"could not get user id: {r.text}"
    return r.json()['data'][0]['login']

def twitch_eventsub(username, subscribe_type):
    user_id = twitch_get_user_id(username)
    data = {
        'version': '1',
        'condition': {
            'broadcaster_user_id': user_id,
        },
        'type': subscribe_type,
        'transport': {
            'secret': 'loltestsecret',
            'method': 'webhook',
            'callback': 'https://streambot.hagesjo.se/webhook',
        }
    }

    r = requests.post("https://api.twitch.tv/helix/eventsub/subscriptions", headers=headers, json=data)
    if r.status_code != 202:
        return r.json()

def twitch_unsubscribe(username):
    user_id = twitch_get_user_id(username)
    for s in twitch_list_subscriptions()['data']:
        if s['condition']['broadcaster_user_id'] == user_id:
            r = requests.delete("http://api.twitch.tv/helix/eventsub/subscriptions", params={'id': s['id']}, headers=headers)
            if r.status_code != 204:
                return r.json()

def twitch_list_subscriptions():
    return requests.get("https://api.twitch.tv/helix/eventsub/subscriptions", headers=headers).json()

app.run(port=5000)
