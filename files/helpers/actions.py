from flask import g
from files.classes.badges import Badge
from files.helpers.alerts import send_repeatable_notification
from files.helpers.const import *
from files.helpers.get import *
from files.helpers.sanitize import *
import random
from urllib.parse import quote

def badge_grant(user, badge_id, description=None, url=None):
	assert user != None
	if user.has_badge(badge_id):
		return

	badge = Badge(
		badge_id=int(badge_id),
		user_id=user.id,
		description=description,
		url=url,
	)

	g.db.add(badge)
	g.db.flush()

	send_repeatable_notification(user.id,
		f"@AutoJanny has given you the following profile badge:\n\n" +
		f"![]({badge.path})\n\n{badge.name}")


def archiveorg(url):
	try: requests.get(f'https://web.archive.org/save/{url}', headers={'User-Agent': 'Mozilla/4.0 (compatible; MSIE 5.5; Windows NT)'}, timeout=100)
	except: pass

def execute_snappy(post, v):
	snappy = get_account(SNAPPY_ID)

	if post.sub == 'dankchristianmemes' or post.sub == 'truth':
		body = random.choice(christian_emojis)
	elif v.id == CARP_ID:
		if random.random() < 0.02: body = "i love you carp"
		else: body = ":#marseyfuckoffcarp:"
	elif v.id == LAWLZ_ID:
		if random.random() < 0.5: body = "wow, this lawlzpost sucks!"
		else: body = "wow, a good lawlzpost for once!"
	elif len(SNAPPY_QUOTES) == 0:
		body = ""
	else:
		body = random.choice(SNAPPY_QUOTES).strip()
		if body.startswith('▼'):
			body = body[1:]
			vote = Vote(user_id=SNAPPY_ID,
						vote_type=-1,
						submission_id=post.id,
						real = True
						)
			g.db.add(vote)
			post.downvotes += 1
			if body.startswith('OP is a Trump supporter'):
				flag = Flag(post_id=post.id, user_id=SNAPPY_ID, reason='Trump supporter')
				g.db.add(flag)
			elif body.startswith('You had your chance. Downvoted and reported'):
				flag = Flag(post_id=post.id, user_id=SNAPPY_ID, reason='Retard')
				g.db.add(flag)
		elif body.startswith('▲'):
			body = body[1:]
			vote = Vote(user_id=SNAPPY_ID,
						vote_type=1,
						submission_id=post.id,
						real = True
						)
			g.db.add(vote)
			post.upvotes += 1
		elif body == '!slots':
			body = f'!slots{snappy.coins}'

	body += "\n\n"

	if post.url:
		if post.url.startswith('https://old.reddit.com/r/'):
			rev = post.url.replace('https://old.reddit.com/', '')
			rev = f"* [unddit.com](https://unddit.com/{rev})\n"
		elif post.url.startswith("https://old.reddit.com/u/"):
			rev = post.url.replace('https://old.reddit.com/u/', '')
			rev = f"* [search.marsey.cat](https://search.marsey.cat/reddit-search/#\u007b\"author\":\"{rev}\",\"resultSize\":100\u007d)\n"
		else: rev = ''
		
		newposturl = post.url
		if newposturl.startswith('/'): newposturl = f"{SITE_FULL}{newposturl}"
		body += f"Snapshots:\n\n{rev}* [archive.org](https://web.archive.org/{newposturl})\n* [archive.ph](https://archive.ph/?url={quote(newposturl)}&run=1) (click to archive)\n* [ghostarchive.org](https://ghostarchive.org/search?term={quote(newposturl)}) (click to archive)\n\n"
		gevent.spawn(archiveorg, newposturl)

	captured = []
	body_for_snappy = post.body_html.replace(' data-src="', ' src="')


	for i in list(snappy_url_regex.finditer(body_for_snappy)):
		href = i.group(1)
		if href in [x[0] for x in captured]: continue
		title = i.group(2)
		captured.append((href, title))

	for i in list(snappy_youtube_regex.finditer(body_for_snappy)):
		href = f'https://youtube.com/watch?v={i.group(1)}'
		if href in [x[0] for x in captured]: continue
		captured.append((href, href))


	for href, title in captured:
		if "Snapshots:\n\n" not in body: body += "Snapshots:\n\n"

		if f'**[{title}]({href})**:\n\n' not in body:
			addition = f'**[{title}]({href})**:\n\n'
			if href.startswith('https://old.reddit.com/r/'):
				rev = href.replace('https://old.reddit.com/', '')
				addition += f'* [unddit.com](https://unddit.com/{rev})\n'
			if href.startswith('https://old.reddit.com/u/'):
				rev = href.replace('https://old.reddit.com/u/', '')
				addition += f"* [search.marsey.cat](https://search.marsey.cat/reddit-search/#\u007b\"author\":\"{rev}\",\"resultSize\":100\u007d)\n"
			addition += f'* [archive.org](https://web.archive.org/{href})\n'
			addition += f'* [archive.ph](https://archive.ph/?url={quote(href)}&run=1) (click to archive)\n'
			addition += f'* [ghostarchive.org](https://ghostarchive.org/search?term={quote(href)}) (click to archive)\n\n'
			if len(f'{body}{addition}') > 10000: break
			body += addition
			gevent.spawn(archiveorg, href)

	body = body.strip()
	body_html = sanitize(body)

	if len(body_html) == 0:
		return

	if len(body_html) < 40000:
		c = Comment(author_id=SNAPPY_ID,
			distinguish_level=6,
			parent_submission=post.id,
			level=1,
			over_18=False,
			is_bot=True,
			app_id=None,
			body=body,
			body_html=body_html,
			ghost=post.ghost
			)

		g.db.add(c)

		snappy.comment_count += 1
		snappy.coins += 1
		g.db.add(snappy)
		
		if body.startswith('!slots'):
			check_for_slots_command(body, snappy, c)

		if PIN_ENABLED and (body.startswith(':#marseypin:') or body.startswith(':#marseypin2:')):
			post.stickied = "Snappy"
			post.stickied_utc = int(time.time()) + 3600

		g.db.flush()

		c.top_comment_id = c.id

		post.comment_count += 1
		post.replies = [c]
