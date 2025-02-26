#!/usr/bin/env python
# -*- coding: utf-8 -*-
import configparser as config
import csv
import hashlib
import io
import logging
import math
import os
import sys
import time

import atproto
import dotenv
import praw
import prawcore
import requests
from PIL import Image
from atproto import models
from atproto_client.models import ids

POSTED_IMAGES_CSV = 'posted_images.csv'
CACHE_FOLDER = 'image_cache'
# this is dumb
LOG = logging.getLogger('bluebot')
LOG.setLevel(logging.DEBUG)
file_handler = logging.FileHandler('bluebot.log')
file_handler.setLevel(logging.DEBUG)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)
LOG.addHandler(file_handler)
LOG.addHandler(console_handler)
LOG.debug("goofy ahh logger test")

parser = config.ConfigParser()
parser.read('config.ini')


dotenv.load_dotenv()

# Check if required environment variables are set
required_vars = ['APU', 'AP', 'CID', 'CS']
for var in required_vars:
    if var not in os.environ:
        LOG.critical(f"Error: {var} environment variable is not set")
        sys.exit(1)


client = atproto.Client()
client.login(os.environ["APU"], os.environ["AP"])

reddit = praw.Reddit(client_id=os.environ["CID"], client_secret=os.environ["CS"],
                     user_agent="linux:bluebot:v0.0.2 (by /u/dariusisdumblol)")


def ImgPrep(image_data):
    if not os.path.exists(CACHE_FOLDER):
        os.makedirs(CACHE_FOLDER)

    image_hash = hashlib.md5(image_data, usedforsecurity=False).hexdigest()

    # lets check if the image is already in the cache
    cache_path = os.path.join(CACHE_FOLDER, image_hash)
    if os.path.exists(cache_path):
        with open(cache_path, 'rb') as f:
            return f.read(), 'image/jpeg'

    # Open the image data with PIL
    image = Image.open(io.BytesIO(image_data))

    # Convert the image to JPEG if not already in a compatible format
    if image.format not in ['JPEG', 'PNG', 'GIF', 'BMP']:
        LOG.info(f"Converting image format from {image.format} to JPEG.")
        output = io.BytesIO()
        image.convert("RGB").save(output, format="JPEG")
        return output.getvalue(), 'image/jpeg'

    with open(cache_path, 'wb') as f:
        f.write(image_data)

    return image_data, 'image/jpeg'


def compress_image(image_data, image_url):
    """
    Compresses an image based on its file type and returns the compressed image data.

    Args:
        image_data (bytes): The binary data of the image to be compressed.
        image_url (str): The URL of the image, used to determine the file type.

    Returns:
        bytes: The binary data of the compressed image.
    """
    # Open the image file
    image = Image.open(io.BytesIO(image_data))

    # Compress the image based on its file type
    output = io.BytesIO()
    if image_url.endswith('.jpg') or image_url.endswith('.jpeg'):
        image.save(output, format="JPEG", quality=80)  # Adjust the quality as needed
    elif image_url.endswith('.png'):
        width, height = image.size
        len(image_data)
        LOG.info("Image size before compression: {}x{} ({} bytes)".format(width, height, len(image_data)))
        new_size = (width // 2, height // 2)
        image.resize(new_size, Image.Resampling.LANCZOS)
        image.save(output, format="JPEG", optimize=True,
                   quality=20)  # jpeg is lossy but its smaller (i wish bsky would support blobs more than 1mb but whatever)
    elif image_url.endswith('.gif'):
        # GIFs are already compressed, so we can't compress them further
        # However, we can still resize them if needed
        image.save(output, format="GIF")
    elif image_url.endswith('.bmp'):
        image.save(output, format="BMP")  # BMPs are not compressible
    maxsize = 976560
    # Check if the image size is greater than the maximum size
    compressed_image_data = output.getvalue()
    return compressed_image_data


def send_post_with_labels(client2, text, labels, embed):
    """
    Sends a post with labels using the given client.

    Args:
        client2 (atproto.Client): The client to use for sending the post.
        text (str): The text of the post.
        labels (models.ComAtprotoLabelDefs.SelfLabels): The labels to apply to the post.
        embed (models.AppBskyEmbedImages.Main): The embed content to include in the post.

    Returns:
        models.ComAtprotoRepoCreateRecord.Response: The response from the server.
    """
    return client2.com.atproto.repo.create_record(
        models.ComAtprotoRepoCreateRecord.Data(
            repo=client2.me.did,
            collection=ids.AppBskyFeedPost,
            record=models.AppBskyFeedPost.Record(
                created_at=client2.get_current_time_iso(),
                text=text,
                labels=labels,
                embed=embed
            ),
        )
    )


def duplicate_check(id):
    value = False
    with open('posted_images.csv', 'rt', newline='') as f:
        reader = csv.reader(f, delimiter=',')
        for row in reader:
            if id in row:
                value = True
    f.close()
    return value


# stolen from gitlab.com/mocchapi/tootbotX
def notify_sleep(sleeptime, interval=5 * 60, reason=""):
    """Sleeps for `sleeptime` amount of time, notifying the user every `interval` seconds.
    Optionally supplied with a `reason`, which gets appended to the first message"""
    timechunk = sleeptime / interval
    timeleft = sleeptime
    LOG.info(f"Sleeping for {round(sleeptime / 60, 1)}m" + reason)
    loop2 = False
    while math.floor(timeleft) > 0:
        zzzz = 0
        if sleeptime > interval:
            zzzz = interval
        else:
            zzzz = timeleft

        if loop2:
            LOG.info(f"{round(timeleft / 60, 1)}m remaining.")
        else:
            loop2 = True
        timeleft -= zzzz
        time.sleep(zzzz)


def get_subreddit():
    """
    Retrieves the subreddit specified in the configuration file.

    Returns:
        praw.models.Subreddit: The subreddit object for the specified subreddit.

    Raises:
        SystemExit: If the 'reddit' section or 'subreddit' key is not found in the config file.
    """
    try:
        sub = parser.get('reddit', 'subreddit')
        LOG.info(f"Trying to access subreddit: {sub}")
        return reddit.subreddit(sub)
    except config.NoSectionError:
        LOG.error("Error: 'reddit' section not found in config file")
        sys.exit(1)
    except config.NoOptionError:
        LOG.error("Error: 'subreddit' key not found in 'reddit' section of config file")
        sys.exit(1)


def main():
    LOG.info("Starting...")
    client.login(os.environ["APU"], os.environ["AP"])

    # this should of been here first lmao
    label = parser.get('bsky', 'label')
    labels = models.ComAtprotoLabelDefs.SelfLabels(
        values=[
            # idk what to do about nude posts on the subreddit so uhhhhh  dm me or smth
            models.ComAtprotoLabelDefs.SelfLabel(val=label),
        ]
    )
    try:
        limit = int(parser.get('reddit', 'limit'))
    except config.NoSectionError:
        LOG.error("Error: 'reddit' section not found in config file")
        sys.exit(1)
    except config.NoOptionError:
        LOG.error("Error: 'limit' key not found in 'reddit' section of config file")
        sys.exit(1)
    except ValueError:
        LOG.error("Error: 'limit' value is not a valid integer")
        sys.exit(1)
    last_post_id = None
    try:
        sub = get_subreddit()
        with open(POSTED_IMAGES_CSV, 'r') as csvfile:
            reader = csv.reader(csvfile)
            posted_images = set(row[0] for row in reader)
        results = []
        new_posts_found = False
        for submission in sub.hot():
            if len(results) >= limit:  # Manually enforce your desired limit here
                continue
            if 'imgur.com' in submission.url:
                LOG.info(f"Skipping Imgur post: {submission.url}")
                continue
            post_id = submission.id
            if not submission.stickied and not submission.is_self and submission.url.endswith(
                    ('.jpg', '.png', '.gif', '.bmp')):
                results.append(submission)
                LOG.info(f"{submission.title} ({submission.author.name})")
                image_url = submission.url
                if not duplicate_check(post_id):
                    image_data = requests.get(image_url, timeout=60).content
                    image_size = len(image_data)
                    max_size = 976560
                    if image_size <= max_size:
                        # TODO: add ocr
                        # client.send_image(
                        #    text=submission.title + " (u/" + submission.author.name + ")" + "  " + submission.source,
                        #    image=image_data,
                        #    image_alt='', )
                        cached_image_data, mime_type = ImgPrep(image_data)
                        upload = client.upload_blob(cached_image_data)
                        images = [models.AppBskyEmbedImages.Image(alt='', image=upload.blob)]
                        embed = models.AppBskyEmbedImages.Main(images=images)
                        send_post_with_labels(client, submission.title + " (u/" + submission.author.name + ")", labels,
                                              embed)
                        with open(POSTED_IMAGES_CSV, 'a') as csvfile:
                            writer = csv.writer(csvfile)
                            writer.writerow([post_id])
                        LOG.info(f"Posted image: {image_url}")
                        lim_dict = reddit.auth.limits
                        LOG.info(lim_dict)  # Only update last_post_id if the submission is new
                        last_post_id = submission.id
                    else:
                        LOG.info(f"Resizing image because it's too big: {image_url}")
                        compressed_image_data = compress_image(image_data, image_url)
                        compressed_image_size = len(compressed_image_data)
                        if compressed_image_size > max_size:
                            LOG.info(f"Skipping image because it's still too big after compression: {image_url}")
                            with open(POSTED_IMAGES_CSV, 'a') as csvfile:
                                writer = csv.writer(csvfile)
                                writer.writerow([post_id])
                            continue
                        else:
                            cached_image_data, mime_type = ImgPrep(compressed_image_data)
                            upload = client.upload_blob(cached_image_data)
                            images = [models.AppBskyEmbedImages.Image(alt='', image=upload.blob)]
                            embed = models.AppBskyEmbedImages.Main(images=images)
                            send_post_with_labels(client, submission.title + " (u/" + submission.author.name + ")",
                                                  labels,
                                                  embed)
                            with open(POSTED_IMAGES_CSV, 'a') as csvfile:
                                writer = csv.writer(csvfile)
                                writer.writerow([post_id])
                            LOG.info(f"Posted compressed image: {image_url}")
                            lim_dict = reddit.auth.limits
                            LOG.info(lim_dict)
                            last_post_id = submission.id
                            LOG.info(f"Image size: {image_size} bytes")
                else:
                    LOG.info(f"Skipping already posted image: {image_url}")
                    continue


    except prawcore.exceptions.NotFound:
        LOG.error("Error: Subreddit not found. Please check the subreddit name in your config file.")


if __name__ == "__main__":
    while True:
        try:
            main()
            notify_sleep(sleeptime=1800, reason=f" (pos)")
        except Exception as e:
            LOG.error(f"Error: {e}")
        time.sleep(10)
