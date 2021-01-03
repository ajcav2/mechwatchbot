import copy
import os
import pickle
import re
import threading
import time
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

class RedditUser():
    def __init__(self, username, message):
        self.username = username
        self.message = message


    def update_messages(self, message):
        self.message = message


    def get_watch_list(self, message):
        user_df = read_df_pickle(user_df_pickle)
        this_user = user_df.loc[self.username]
        body = 'Your current watch list for /r/mechmarket is:\n\n'
        item_counter = 1
        for item in this_user['h']:
            body += str(item_counter)+'. [H] '+item+'\n\n'
            item_counter += 1
        for item in this_user['w']:
            body += str(item_counter)+'. [W] '+item+'\n\n'
            item_counter += 1
        for item in this_user['ic']:
            body += str(item_counter)+'. [IC] '+item+'\n\n'
            item_counter += 1
        for item in this_user['v']:
            body += str(item_counter)+'. [V] '+item+'\n\n'
            item_counter += 1
        for item in this_user['gb']:
            body += str(item_counter)+'. [GB] '+item+'\n\n'
            item_counter += 1
        self.send_message(body)


    def get_help(self, message):
        self.send_message('This bot searches post titles in the /r/mechmarket subreddit.\
                           When the bot finds a match between your watch list and a post title, \
                           it\'ll send you a message with a link to the post. For example, if you\'re \
                           looking for posts where people are selling "GMK alphas", you could send the \
                           bot `/h gmk alphas`. If you\'re looking to follow group buys for acrylic cases, \
                           send the bot `/gb acrylic case`, or simply just `/gb acrylic`. The available bot commands are as follows:  \n\n'+
                                                        '`/h <search_term>` : : watch the _have_ section  \n\n'+
                                                        '`/w <search_term>` : : watch the _want_ section  \n\n'+
                                                        '`/v <search_term>` : : watch for vendor  \n\n'+
                                                        '`/gb <search_term>` : : watch for group buy  \n\n'+
                                                        '`/ic <search_term>` : : watch for interest check  \n\n'+
                                                        '`/rm <search_term>` : : remove search_term from watch list  \n\n'+
                                                        '`/va` : : view all watch list \n\n'+
                                                        '`/br` <description> : : report a bug or suggest a feature!')


    def alert_author(self, title, submission):
        self.send_message(f'One of your /r/mechmarket alerts has been trigged!\n\n{title}\n\n{submission.permalink}')


    def send_message(self, body):
        reddit.inbox.message(self.message).reply(body)


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


def alert_interested_users(user_df, user_column, title_text, submission):
    users = user_df.loc[[any(x in title_text for x in y) for y in user_df[user_column].tolist()]]
    for index, row in users.iterrows():
        print(f"Alerting {user_df.loc[index].name} to {submission.title}", flush=True)
        user_df.loc[index]['RedditUser'].alert_author(submission.title, submission)


def inbox_monitor():
    for item in reddit.inbox.stream(skip_existing=True):
        user_df = read_df_pickle(user_df_pickle)

        message = reddit.inbox.message(item.id)
        author = message.author.name
        command = message.body

        print(f"{author}: {command}", flush=True)
        if author in user_df.index.tolist():
            user_df.loc[author]['RedditUser'].update_messages(message)
        else:
            user_df.loc[author] = [RedditUser(author, message), [], [], [], [], []]

        print(f"Number of users: {len(user_df)}", flush=True)
        this_user = user_df.loc[author]['RedditUser']
        if command.lower().startswith('/help'):
            this_user.get_help(message)
        elif command.lower().startswith('/va'):
            this_user.get_watch_list(message)
        elif command.lower().startswith('/rm'):
            rm_item = command[3:].lower().strip()
            for c in user_df.loc[author]:
                try:
                    if rm_item in c:
                        c.remove(rm_item)
                        this_user.send_message(f"Removed {rm_item} from watchlist.")
                except TypeError:
                    pass
            write_df_pickle(user_df_pickle, user_df)
            this_user.get_watch_list(message)
        elif command[0:3].lower().strip() in ['/h', '/w', '/gb', '/ic', '/v']:
            new_item = command[3:].lower().strip()
            if new_item.startswith('<') and new_item.endswith('>'):
                new_item = new_item[1:-1]
            watch_type = command[1:3].lower().strip()
            if new_item not in user_df.loc[author][watch_type]:
                user_df.loc[author][watch_type].append(new_item)
                this_user.send_message(f"Got it. Watching for [{watch_type.upper()}] {new_item.title()} in /r/mechmarket!")
            else:
                this_user.send_message(f"{new_item} already in watch list!")
            write_df_pickle(user_df_pickle, user_df)
            this_user.get_watch_list(message)
        elif command[0:3].lower().strip() == '/br':
            record_bug(author, command[3:].lower().strip())
            this_user.send_message("Thanks for your feedback!")
        else:
            this_user.get_help(message)


def record_bug(author, description):
    with open('bug_reports.txt', 'a+') as f:
        f.write(f"{author}: {description}\r\n")


def analyze_submission(submission):
    user_df = read_df_pickle(user_df_pickle)

    title = submission.title.lower()
    print(f"Searching title: {submission.title}", flush=True)
    t = time.time()
    if trading_regex.search(title):
        m = trading_regex.search(title)
        alert_interested_users(user_df, 'w', m.group('want'), submission)
        alert_interested_users(user_df, 'h', m.group('have'), submission)
    elif groupbuy_regex.search(title):
        alert_interested_users(user_df, 'gb', groupbuy_regex.search(title).group('title'), submission)
    elif vendor_regex.search(title):
        alert_interested_users(user_df, 'v', vendor_regex.search(title).group('title'), submission)
    elif ic_regex.search(title):
        alert_interested_users(user_df, 'ic', ic_regex.search(title).group('title'), submission)
    print(f"Finished regex search and alerts in {round(time.time()-t, 1)} seconds", flush=True)


if __name__ == "__main__":
    if os.path.exists(user_df_pickle+'.lock'):
        os.remove(user_df_pickle+'.lock')

    try:
        inbox_monitor_proc = Process(target=inbox_monitor)
        inbox_monitor_proc.start()

        while True:
            try:
                for submission in reddit.subreddit("mechmarket").stream.submissions(skip_existing=True):
                    subreddit_watch_proc = Process(target=analyze_submission, args=(submission, ))
                    subreddit_watch_proc.start()
            except praw.exceptions.RedditAPIException as e:
                print(e, flush=True)

    except praw.exceptions.RedditAPIException as e:
        print(e, flush=True)
    finally:
        inbox_monitor_proc.terminate()
