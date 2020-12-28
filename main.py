import praw
from multiprocessing import Process
import time
import threading
import re
import copy
import pickle

reddit = praw.Reddit("mechwatchbot")
subreddit = reddit.subreddit('mechmarket')

trading_regex = re.compile(r'\[h\](?P<have>.*?)\[w\](?P<want>.*)')
vendor_regex = re.compile(r'\[vendor\](?P<title>.*)')
groupbuy_regex = re.compile(r'\[gb\](?P<title>.*)')

c = threading.Condition()
user_dict = {}

class RedditUser():
    def __init__(self, username, message):
        self.username = username
        self.messages = [message]
        self.watch_list = {'h': [], 'w': [], 'v': [], 'gb': [], 'ic': []}


    def update_messages(self, message):
        self.messages.append(message)


    def add_to_watchlist(self, message, item_type, item):
        if item not in self.watch_list[item_type]:
            self.watch_list[item_type].append(item)
            self.send_message(f"Added {item} to your watchlist.")
        else:
            self.send_message(f"{item.capitalize()} already in watchlist.")
        self.get_watch_list(message)


    def get_watch_list(self, message):
        body = 'Your current watch list for /r/mechmarket is:\n\n'
        item_counter = 1
        for watch_type, item_list in self.watch_list.items():
            for item in item_list:
                body += str(item_counter)+'. ['+watch_type.upper()+'] '+item+'\n\n'
                item_counter += 1
        self.send_message(body)

    
    def get_help(self, message):
        self.send_message('This bot searches for strings inside of posts on the mechmarket subreddit. \
                                                         The available bot commands are as follows:  \n\n'+
                                                        '`/h <string>` :: watch the _have_ section  \n\n'+
                                                        '`/w <string>` :: watch the _want_ section  \n\n'+
                                                        '`/v <string>` :: watch for vendor  \n\n'+
                                                        '`/gb <string>` :: watch for group buy  \n\n'+
                                                        '`/ic <string>` :: watch for interest check  \n\n'+
                                                        '`/rm <string>` :: remove string from watch list  \n\n'+
                                                        '`/va` :: view all watch list')


    def alert_author(self, item, submission):
        self.send_message(f'Your watch notification for {item} has been triggered by {submission.permalink}')


    def remove_item(self, message, rm_item):
        for watch_type, item_list in self.watch_list.items():
            try:
                self.watch_list[watch_type].remove(rm_item)
            except ValueError:
                pass
        self.get_watch_list(message)


    def send_message(self, body):
        reddit.inbox.message(self.messages[-1]).reply(body)



class InboxThread(threading.Thread):
    def __init__(self, name):
        threading.Thread.__init__(self)
        self.name = name

    def run(self):
        global user_dict
        user_list_pickle = 'userlist.pickle'
        
        for item in reddit.inbox.stream(skip_existing=True):
            c.acquire()

            with open(user_list_pickle, 'rb') as f:
                user_dict = pickle.load(f)

            message = reddit.inbox.message(item.id)
            author = message.author.name
            command = message.body

            print(f"{author}: {command}")
            if author not in user_dict:
                user_dict[author] = RedditUser(author, message)
            else:
                user_dict[author].update_messages(message)


            if command.lower().startswith('/help'):
                user_dict[author].get_help(message)
            elif command.lower().startswith('/va'):
                user_dict[author].get_watch_list(message)
            elif command.lower().startswith('/rm'):
                rm_item = command[3:].lower().strip()
                user_dict[author].remove_item(message, rm_item)
            elif command[0:3].lower().strip() in ['/h', '/w', '/gb', '/ic', '/v']:
                new_item = command[3:].lower().strip()
                watch_type = command[1:3].lower().strip()
                user_dict[author].add_to_watchlist(message, watch_type, new_item)
            else:
                user_dict[author].get_help(message)

            with open(user_list_pickle, 'wb') as f:
                pickle.dump(user_dict, f, protocol=pickle.HIGHEST_PROTOCOL)

            c.notify_all()
            c.release()


class WatchThread(threading.Thread):
    def __init__(self, name):
        threading.Thread.__init__(self)
        self.name = name

    def run(self):
        global user_dict

        for submission in reddit.subreddit("mechmarket").stream.submissions(skip_existing=True):
            c.acquire()
            t_user_dict = copy.deepcopy(user_dict)
            c.notify_all()
            c.release()

            while len(t_user_dict) == 0:
                c.acquire()
                t_user_dict = copy.deepcopy(user_dict)
                c.notify_all()
                c.release()

            title = submission.title.lower()
            print(f"Searching title: {submission.title}")
            t = time.time()
            if trading_regex.search(title):
                m = trading_regex.search(title)
                have = m.group('have')
                want = m.group('want')
                for author in t_user_dict:
                    for watched_item in t_user_dict[author].watch_list['h']:
                        if watched_item in have:
                            print(f"Alerting {author} about {watched_item}")
                            t_user_dict[author].alert_author(watched_item, submission)
                    for item_to_be_sold in t_user_dict[author].watch_list['w']:
                        if item_to_be_sold in want:
                            print(f"Alerting {author} about {item_to_be_sold}")
                            t_user_dict[author].alert_author(item_to_be_sold, submission)
            elif groupbuy_regex.search(title):
                gb_text = groupbuy_regex.search(title).group('title')
                for author in t_user_dict:
                    for groupbuy_item in t_user_dict[author].watch_list['gb']:
                        if groupbuy_item in gb_text:
                            print(f"Alerting {author} about {groupbuy_item}")
                            t_user_dict[author].alert_author(groupbuy_item, submission)
            elif vendor_regex.search(title):
                vendor_text = vendor_regex.search(title).group('title')
                for author in t_user_dict:
                    for vendor in t_user_dict[author].watch_list['v']:
                        if vendor in vendor_text:
                            print(f"Alerting {author} about {vendor} post")
                            t_user_dict[author].alert_author(vendor, submission)
            print(f"Finished regex search in {time.time()-t} seconds")

a = InboxThread("InboxThread")
b = WatchThread("WatchThread")

b.start()
a.start()

a.join()
b.join()
