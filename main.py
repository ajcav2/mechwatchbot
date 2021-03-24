import copy
import os
import pickle
import re
import threading
import time
import traceback
from multiprocessing import Process

import pandas as pd
import praw

reddit = praw.Reddit("mechwatchbot")
subreddit = reddit.subreddit('mechmarket')
user_df_pickle = 'userlist.pickle'

trading_regex = re.compile(r'\[h\](?P<have>.*?)\[w\](?P<want>.*)')
vendor_regex = re.compile(r'\[vendor\](?P<title>.*)')
groupbuy_regex = re.compile(r'\[gb\](?P<title>.*)')
ic_regex = re.compile(r'\[ic\](?P<title>.*)')

watchlist_ordered_types = ['h', 'w', 's', 'ic', 'v', 'gb']


def is_valid_command(text):
    if text.startswith('/va') or text.startswith('/unsub') or text.startswith('/help') or text.startswith('/n') or text.startswith('/l'):
        return True
    elif text.split()[0] in ['/h', '/w', '/s', '/v', '/l', '/br', '/gb', '/ic', '/rm'] and text[4:] and not text[4:].isspace():
        return True
    return False


def get_formatted_watch_list_string(watch_type, item, item_count):
    formatted_substring = \
        f'[H] {item} + [W] Paypal' if watch_type == 's' else f'[{watch_type.upper()}] {item}'
    return f'{item_count}. {formatted_substring}\n\n'


def send_watch_list(reddit_user):
    body = 'Your current watch list for /r/mechmarket is:\n\n'
    item_count = 1
    for watch_type in watchlist_ordered_types:
        for item in reddit_user.loc[watch_type]:
                body += get_formatted_watch_list_string(watch_type, item, item_count)
                item_count += 1

    body += f"Your current location is: {reddit_user.loc['l'].upper() if reddit_user.loc['l'] else 'Earth'}"
    reddit.inbox.message(reddit_user.thread_id).reply(body)


def send_alert(reddit_user, submission):
    reddit.inbox.message(reddit_user.thread_id).reply(f'One of your /r/mechmarket alerts has been triggered!\n\n{submission.title}\n\n{submission.permalink}')


def send_message(reddit_user, message):
    reddit.inbox.message(reddit_user.thread_id).reply(message)


def send_remove_message(reddit_user, removed_item):
    reddit.inbox.message(reddit_user.thread_id).reply(f"Removed {removed_item} from watchlist.")


def send_number_of_users(reddit_user):
    user_df = read_df_pickle(user_df_pickle)
    send_message(reddit_user, f"Number of users: {len(user_df)}")


def send_help(reddit_user):
    reddit.inbox.message(reddit_user.thread_id).reply('This bot searches post titles in the /r/mechmarket subreddit.\
                    When the bot finds a match between your watch list and a post title, \
                    it\'ll send you a message with a link to the post. For example, if you\'re \
                    looking for posts where people are selling "GMK alphas", you could send the \
                    bot `/h gmk alphas`. If you\'re looking to follow group buys for acrylic cases, \
                    send the bot `/gb acrylic case`, or simply just `/gb acrylic`. See the table below for available commands:  \n\n'+
                    '''Command | Description | Example
                    -|-|-
                    `/h search_term` | Search for posts where people _have_ \[H] the search_term. Only one of `/h` \
                    and `/s` can apply to a given item. | `/h Olivia++`
                    `/s search_term` | Search for posts where people _have_ \[H] the search\_term and _want_ \[W] Paypal. Only one of `/h` \
                    and `/s` can apply to a given item. | `/s Botanical`
                    `/w search_term` | Search for posts where people _want_ \[W] the search_term | `/w Lily58`
                    `/v search_term` | Search for posts from a specific vendor \[Vendor] | `/v VintKeys` |
                    `/ic search_term` | Search for posts advertising an interest check \[IC] | `/ic Acrylic Case`
                    `/gb search_term` | Search for posts advertising a group buy \[GB] | `/gb Artisan Spacebar`
                    `/rm search_term` | Remove a search term from your watch list | `/rm Blanks`
                    `/rm list_index` | Remove watch list item by number | `/rm 3`
                    `/l location` | [location code](https://www.reddit.com/r/mechmarket/wiki/rules/rules) for trades| `/l US-IL`
                    `/va` | View your current watch list | `/va`
                    `/help` | Show available commands | `/help`
                    `/br description` | Submit a bug or feature request | `/br Track services, too!`
                    `/unsub` | Unsubscribe from all alerts | `/unsub`\n\nIf you find this bot helpful, you can support development by \
                    [buying me a coffee :)](https://www.buymeacoffee.com/mechwatchbot). Running the server costs me $5/month \
                    on [pythonanywhere](https://www.pythonanywhere.com/pricing/) and \
                    lots of development time. Thanks!''')


def is_allowable_trade_location(user_df_row, submission):
	return not user_df_row['l'] or '['+user_df_row['l'].lower() in submission.title.lower()


def lock_controlled_file(func):
    def wrap(*args, **kwargs):
        while os.path.exists(args[0]+'.lock'):
            time.sleep(1)
        with open(args[0]+'.lock', 'w+') as f:
            pass
        result = func(*args, **kwargs)
        while os.path.exists(args[0]+'.lock'):
            os.remove(args[0]+'.lock')
        return result
    return wrap


@lock_controlled_file
def read_df_pickle(fp):
    return pd.read_pickle(fp)


@lock_controlled_file
def write_df_pickle(fp, df):
    df.to_pickle(fp, protocol=pickle.HIGHEST_PROTOCOL)

def alert_interested_users(post_type, title_text, submission):
    user_df = read_df_pickle(user_df_pickle)

    # Filter by items
    users = user_df.loc[[any(x in title_text for x in y) for y in user_df[post_type].tolist()]]
    users_alerted = []
    for index, row in users.iterrows():
        # Filter by location for trades and selling
        if post_type in ['h', 'w', 's'] and not is_allowable_trade_location(row, submission):
        	continue
        else:
            users_alerted.append(row.name)
            send_alert(row, submission)

    if len(users_alerted) > 0:
        print(f"Alerting {', '.join([user for user in users_alerted])} to {submission.title}", flush=True)


def parse_commands(reddit_user, msg):
    commands = []
    for line in re.sub(r'\n+', '\n', msg.body).strip().split('\n'):
        if is_valid_command(line):
            res = line.split(' ', 1)
            if len(res) > 1:
                commands.append((res[0].lower(), res[1].lower()))
            else:
                commands.append((res[0].lower(), ''))
        else:
            send_message(reddit_user, f"Sorry, I didn't understand your command:\n\n{line}\n\nReply `/help` for help.")
    return commands


def update_thread_id(author, message):
    user_df = read_df_pickle(user_df_pickle)
    if author in user_df.index.tolist():
        user_df.loc[author]['thread_id'] = message
    else:
        user_df.loc[author] = [message, [], [], [], [], [], [], None]
    write_df_pickle(user_df_pickle, user_df)


def unsubscribe_user(reddit_user):
    user_df = read_df_pickle(user_df_pickle)
    user_df = user_df.drop([reddit_user.name])
    write_df_pickle(user_df_pickle, user_df)
    send_message(reddit_user, f"Bye, {reddit_user.name}! Send me another message if you want to opt back in to alerts :)")


def add_item_to_watch_list(reddit_user, command):
    user_df = read_df_pickle(user_df_pickle)

    new_item = command[1]
    if new_item.startswith('<') and new_item.endswith('>'):
        send_message(reddit_user, "Just a heads up, you don't need the angle brackets <> around your search term. I removed them for you :)")
        new_item = new_item[1:-1]
    watch_type = command[0][1:].lower()
    if new_item not in user_df.loc[reddit_user.name][watch_type]:
        user_df.loc[reddit_user.name][watch_type].append(new_item)
        if command[0] == '/s':
            send_message(reddit_user, f"Got it. Watching for [H] {new_item.title()} + [W] Paypal in /r/mechmarket!")
        else:
            send_message(reddit_user, f"Got it. Watching for [{watch_type.upper()}] {new_item.title()} in /r/mechmarket!")
    else:
        send_message(reddit_user, f"{new_item} already in watch list!")

    # Dedupe /h and /s to avoid duplicate messages.
    if command[0] in ['/h', '/s'] and new_item in user_df.loc[reddit_user.name]['h'] and new_item in user_df.loc[reddit_user.name]['s']:
        user_df.loc[reddit_user.name]['h' if command[0] == '/s' else 's'].remove(new_item)
        send_message(reddit_user, f"Overriding overlapping `{'/h' if command[0] == '/s' else '/s'}` {new_item} command. \
            Only one of `/h` and `/s` can apply to a given item.")
    
    write_df_pickle(user_df_pickle, user_df)
    send_watch_list(reddit_user)


def remove_item_from_watch_list(reddit_user, command):
    user_df = read_df_pickle(user_df_pickle)
    rm_item = command[1].strip()
    did_remove_item = False
    try:
        index = int(rm_item)-1
        user_df = remove_item_by_index(reddit_user.name, index)
        did_remove_item = True
    except (IndexError, ValueError):
        for c in user_df.loc[reddit_user.name]:
            try:
                if rm_item in c:
                    c.remove(rm_item)
                    send_message(reddit_user, f"Removed {rm_item} from watch list.")
                    did_remove_item = True
            except TypeError:
                pass

    if not did_remove_item:
        send_message(reddit_user, f"Sorry, I couldn't find {command[1]} in your watch list! Reply `/va` to see your list.")
    write_df_pickle(user_df_pickle, user_df)


def remove_item_by_index(author, index):
    # Get user row from dataframe
    user_df = read_df_pickle(user_df_pickle)
    this_user = user_df.loc[author]

    # Find the item to remove and remove it
    index_counter = 0
    length_so_far = 0
    lengths_in_order = [len(this_user.loc[x]) for x in watchlist_ordered_types]
    for i, this_length in enumerate(lengths_in_order):
        if index < length_so_far+this_length:
            removed_item = user_df.loc[author][watchlist_ordered_types[i]].pop(index-length_so_far)
            send_remove_message(user_df.loc[author], removed_item)
            return user_df
        else:
            length_so_far += this_length

    # If we've reached this point, the user has entered a number larger than the length
    # of their watch list
    send_message(this_user, "You don't have that many items in your watch list! Send `/va` to see your list.")
    return user_df


def update_user_location(reddit_user, command):
    user_df = read_df_pickle(user_df_pickle)
    location = command[1] # TODO: Validate location
    user_df.loc[reddit_user.name]['l'] = location
    if location:
        send_message(reddit_user, f"I set your location to {location.upper()}. Send `/l` to unset your location filter for trades.")
    else:
        send_message(reddit_user, f"Removed location filter.")
    write_df_pickle(user_df_pickle, user_df)


def record_bug(reddit_user, description):
    with open('bug_reports.txt', 'a+') as f:
        f.write(f"{reddit_user.name}: {description}\r\n")
    send_message(reddit_user, "Thanks for your feedback!")


def analyze_submission(submission):
    user_df = read_df_pickle(user_df_pickle)

    title = submission.title.lower()
    print(f"Searching title: {submission.title}", flush=True)
    t = time.time()
    if trading_regex.search(title):
        m = trading_regex.search(title)
        alert_interested_users('w', m.group('want'), submission)
        alert_interested_users('h', m.group('have'), submission)
        if selling_regex.search(title):
        	alert_interested_users('s', selling_regex.search(title).group('have'), submission)
    elif groupbuy_regex.search(title):
        alert_interested_users('gb', groupbuy_regex.search(title).group('title'), submission)
    elif vendor_regex.search(title):
        alert_interested_users('v', vendor_regex.search(title).group('title'), submission)
    elif ic_regex.search(title):
        alert_interested_users('ic', ic_regex.search(title).group('title'), submission)
    print(f"Finished regex search and alerts in {round(time.time()-t, 1)} seconds", flush=True)
    

def inbox_monitor():
    while True:
        try:
            for item in reddit.inbox.stream(skip_existing=True):
                message = reddit.inbox.message(item.id)
                author = message.author.name
                update_thread_id(author, message)
                user_df = read_df_pickle(user_df_pickle)
                this_user = user_df.loc[author]

                commands = parse_commands(this_user, message)
                if [command[0] for command in commands].count('/rm') > 1:
                    # TODO: Implement ability to remove multiple items at once.
                    # Currently, indexing gets messy if the user removes an item
                    # with a smaller index first, followed by a second index
                    # (since they all shift after the first one is removed).
                    send_message(this_user, "Please separate `/rm` commands into multiple messages. Thanks!")
                    continue

                for command in commands:
                    print(f"{author}: {' '.join(command)}", flush=True)
                    
                    if command[0] == '/help':
                        send_help(this_user)
                    elif command[0] == '/va':
                        send_watch_list(this_user)
                    elif command[0] == '/unsub':
                        unsubscribe_user(this_user)
                    elif command[0] == '/n':
                        send_number_of_users(this_user)
                    elif command[0] in ['/h', '/w', '/gb', '/ic', '/v', '/s']:
                        add_item_to_watch_list(this_user, command)
                    elif command[0] == '/rm':
                        remove_item_from_watch_list(this_user, command)
                    elif command[0] == '/br':
                        record_bug(this_user, command[1])
                    elif command[0] == '/l':
                        update_user_location(this_user, command)
                    elif command[0].lower() == '/n':
                        send_number_of_users(this_user)
                    else:
                        send_message(this_user, "Sorry, I didn't understand your command. Send `/help` to see available commands.")
        except Exception as e:
            print(f"Error processing inbox: {e}\n{traceback.print_exc()}\n", flush=True)


if __name__ == "__main__":
    if os.path.exists(user_df_pickle+'.lock'):
        os.remove(user_df_pickle+'.lock')

    inbox_monitor_proc = Process(target=inbox_monitor)
    inbox_monitor_proc.start()

    while True:
        try:
            for submission in reddit.subreddit("mechmarket").stream.submissions(skip_existing=True):
                subreddit_watch_proc = Process(target=analyze_submission, args=(submission, ))
                subreddit_watch_proc.start()
        except Exception as e:
            print(e, flush=True)
