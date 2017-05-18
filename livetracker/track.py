# encoding: utf-8

import sys
import os
import json
from datetime import datetime
from twython import TwythonStreamer
import time
import signal
import timeit
import couchdb

QUERY = os.getenv("TWITTER_TRACKING_QUERY")
TWITTER_CONSUMER_KEY = os.getenv("TWITTER_CONSUMER_KEY")
TWITTER_CONSUMER_SECRET = os.getenv("TWITTER_CONSUMER_SECRET")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_TOKEN_SECRET = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")
COUCHDB_URL = os.getenv("COUCHDB_URL")

unauthorized_backoff_time = 60 * 60  # seconds

class UnauthorizedError(Exception):
    def __init__(self, message):
        # Call the base class constructor with the parameters it needs
        super(UnauthorizedError, self).__init__(message)


def sigterm_handler(_signo, _stack_frame):
    print("Terminating due to SIGTERM")
    sys.exit(0)

class MyStreamer(TwythonStreamer):
    def on_success(self, data):
        if 'id' not in data:
            if "limit" in data:
                q = float(self.tweet_count) / float(self.tweet_count + data["limit"]["track"])
                print("Processed %d tweets, missed %d so far (%.2f%%)" % (
                    self.tweet_count, data["limit"]["track"], q * 100.0))
                return
            sys.stderr.write("Discarded empty tweet:\n")
            sys.stderr.write(json.dumps(data) + "\n")
            return
        else:
            self.tweet_count += 1
        if 'text' not in data:
            sys.stderr.write("Discarded message without text\n")
            return
        process_tweet(data)

    def on_error(self, status_code, data):
        if str(status_code) == "401":
            raise UnauthorizedError("401 Error received")
        else:
            raise Exception("ERROR %s - %s\n" % (status_code, data))


def process_tweet(data):
    data["_id"] = data["id_str"]
    del data["id"]
    del data["id_str"]

    # TODO: remove keys with empty value to save space

    if "_id" in db:
        print('Skipped https://twitter.com/%s/status/%s - already exists' % (data["user"]["screen_name"], data["_id"]))
        return

    try:
        db.save(data)
        print('Saved https://twitter.com/%s/status/%s' % (data["user"]["screen_name"], data["_id"]))
    except Exception, e:
        sys.stderr.write("Error: %s\n" % e)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, sigterm_handler)

    for variable in (TWITTER_CONSUMER_KEY, TWITTER_CONSUMER_SECRET, TWITTER_ACCESS_TOKEN,
        TWITTER_ACCESS_TOKEN_SECRET, COUCHDB_URL):
        if variable is None:
            sys.stderr.write("ERROR: environment variable '%s' is not set.\n")
            sys.exit(1)

    couch = couchdb.Server(COUCHDB_URL)

    db = None
    if 'tweets' in couch:
        db = couch['tweets']
    else:
        db = couch.create('tweets')

    stream = MyStreamer(TWITTER_CONSUMER_KEY,
        TWITTER_CONSUMER_SECRET,
        TWITTER_ACCESS_TOKEN,
        TWITTER_ACCESS_TOKEN_SECRET)
    MyStreamer.tweet_count = 0

    try:
        while True:
            try:
                print "Starting tweet tracking for query '%s'" % QUERY
                stream.statuses.filter(track=QUERY)
            except UnauthorizedError, e:
                # back off for a long period
                sys.stderr.write("Received UnauthorizedError. Backing off for %d seconds.\n" % unauthorized_backoff_time)
                time.sleep(unauthorized_backoff_time)
            except Exception, e:
                sys.stderr.write("Error: %s.\n" % e)
                time.sleep(3)
    finally:
        print("Exiting")
