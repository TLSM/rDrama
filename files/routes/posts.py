import os
import time
from io import BytesIO
from os import path
from shutil import copyfile
from sys import stdout
from urllib.parse import ParseResult, quote, unquote, urlparse, urlunparse

import gevent
import requests
from PIL import Image

from files.__main__ import app, cache, limiter
from files.classes import *
from files.helpers.actions import *
from files.helpers.alerts import *
from files.helpers.const import *
from files.helpers.discord import *
from files.helpers.get import *
from files.helpers.regex import *
from files.helpers.sanitize import *
from files.helpers.settings import get_setting
from files.helpers.slots import *
from files.helpers.sorting_and_time import *
from files.routes.routehelpers import execute_shadowban_viewers_and_voters
from files.routes.wrappers import *

from .front import frontlist
from .users import userpagelisting

from files.__main__ import app, limiter

titleheaders = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.72 Safari/537.36"}

@app.post("/club_post/<pid>")
@feature_required('COUNTRY_CLUB')
@auth_required
def club_post(pid, v):
	post = get_post(pid)
	if post.author_id != v.id and v.admin_level < PERMS['POST_COMMENT_MODERATION']: abort(403)

	if not post.club:
		post.club = True
		g.db.add(post)

		if post.author_id != v.id:
			ma = ModAction(
				kind = "club_post",
				user_id = v.id,
				target_submission_id = post.id,
			)
			g.db.add(ma)

			message = f"@{v.username} (Admin) has marked [{post.title}]({post.shortlink}) as {CC_TITLE}!"
			send_repeatable_notification(post.author_id, message)

	return {"message": f"Post has been marked as {CC_TITLE}!"}

@app.post("/unclub_post/<pid>")
@feature_required('COUNTRY_CLUB')
@auth_required
def unclub_post(pid, v):
	post = get_post(pid)
	if post.author_id != v.id and v.admin_level < PERMS['POST_COMMENT_MODERATION']: abort(403)

	if post.club:
		post.club = False
		g.db.add(post)

		if post.author_id != v.id:
			ma = ModAction(
				kind = "unclub_post",
				user_id = v.id,
				target_submission_id = post.id,
			)
			g.db.add(ma)

			message = f"@{v.username} (Admin) has unmarked [{post.title}]({post.shortlink}) as {CC_TITLE}!"
			send_repeatable_notification(post.author_id, message)

	return {"message": f"Post has been unmarked as {CC_TITLE}!"}


@app.post("/publish/<pid>")
@limiter.limit(DEFAULT_RATELIMIT_SLOWER)
@auth_required
@ratelimit_user()
def publish(pid, v):
	post = get_post(pid)
	if not post.private: return {"message": "Post published!"}

	if post.author_id != v.id: abort(403)
	post.private = False
	post.created_utc = int(time.time())
	g.db.add(post)
	
	if not post.ghost:
		notify_users = NOTIFY_USERS(f'{post.title} {post.body}', v)

		if notify_users:
			cid = notif_comment2(post)
			for x in notify_users:
				add_notif(cid, x)


	cache.delete_memoized(frontlist)
	cache.delete_memoized(userpagelisting)

	if post.sub == 'changelog':
		send_changelog_message(post.permalink)

	if SITE == 'watchpeopledie.tv':
		send_wpd_message(post.permalink)

	execute_snappy(post, v)

	if is_site_url(request.referrer):
		return redirect(request.referrer)

	return redirect(post.permalink)

@app.get("/submit")
@app.get("/h/<sub>/submit")
@auth_required
def submit_get(v, sub=None):
	sub = get_sub_by_name(sub, graceful=True)
	if request.path.startswith('/h/') and not sub: abort(404)

	SUBS = [x[0] for x in g.db.query(Sub.name).order_by(Sub.name).all()]

	return render_template("submit.html", SUBS=SUBS, v=v, sub=sub)

@app.get("/post/<pid>")
@app.get("/post/<pid>/<anything>")
@app.get("/h/<sub>/post/<pid>")
@app.get("/h/<sub>/post/<pid>/<anything>")
@auth_desired_with_logingate
def post_id(pid, anything=None, v=None, sub=None):
	post = get_post(pid, v=v)
	if not User.can_see(v, post): abort(403)
	if not User.can_see_content(v, post) and post.club: abort(403)

	if post.over_18 and not (v and v.over_18) and session.get('over_18', 0) < int(time.time()):
		if g.is_api_or_xhr: return {"error":"Must be 18+ to view"}, 451
		return render_template("errors/nsfw.html", v=v)

	if post.new or 'megathread' in post.title.lower(): defaultsortingcomments = 'new'
	elif v: defaultsortingcomments = v.defaultsortingcomments
	else: defaultsortingcomments = "hot"
	sort = request.values.get("sort", defaultsortingcomments)

	if v:
		execute_shadowban_viewers_and_voters(v, post)
		# shadowban check is done in sort_objects
		# output is needed: see comments.py
		comments, output = get_comments_v_properties(v, True, None, Comment.parent_submission == post.id, Comment.level < 10)
		pinned = [c[0] for c in comments.filter(Comment.stickied != None).all()]
		comments = comments.filter(Comment.level == 1, Comment.stickied == None)
		comments = sort_objects(sort, comments, Comment,
			include_shadowbanned=(v and v.can_see_shadowbanned))
		comments = [c[0] for c in comments.all()]
	else:
		pinned = g.db.query(Comment).filter(Comment.parent_submission == post.id, Comment.stickied != None).all()

		comments = g.db.query(Comment).filter(
				Comment.parent_submission == post.id,
				Comment.level == 1,
				Comment.stickied == None
			)

		comments = sort_objects(sort, comments, Comment,
			include_shadowbanned=False)

		comments = comments.all()

	offset = 0
	ids = set()

	threshold = 100

	if post.comment_count > threshold+25 and not (v and v.client) and not request.values.get("all"):
		comments2 = []
		count = 0
		if post.created_utc > 1638672040: # TODO: migrate old comments to use top_comment_id
			for comment in comments:
				comments2.append(comment)
				ids.add(comment.id)
				count += g.db.query(Comment).filter_by(parent_submission=post.id, top_comment_id=comment.id).count() + 1
				if count > threshold: break
		else:
			for comment in comments:
				comments2.append(comment)
				ids.add(comment.id)
				count += g.db.query(Comment).filter_by(parent_submission=post.id, parent_comment_id=comment.id).count() + 1
				if count > 20: break

		if len(comments) == len(comments2): offset = 0
		else: offset = 1
		comments = comments2

	pinned2 = set()
	for pin in pinned:
		if pin.stickied_utc and int(time.time()) > pin.stickied_utc:
			pin.stickied = None
			pin.stickied_utc = None
			g.db.add(pin)
		elif pin.level > 1:
			pinned2.add(pin.top_comment(g.db))
			if pin.top_comment(g.db) in comments:
				comments.remove(pin.top_comment(g.db))
		else:
			pinned2.add(pin)

	pinned = list(pinned2)
	post.replies = pinned + comments

	post.views += 1
	g.db.add(post)

	if v and v.client:
		return post.json(g.db)

	template = "submission.html"
	if (post.is_banned or post.author.shadowbanned) \
			and not (v and (v.admin_level >= PERMS['POST_COMMENT_MODERATION'] or post.author_id == v.id)):
		template = "submission_banned.html"

	return render_template(template, v=v, p=post, ids=list(ids),
		sort=sort, render_replies=True, offset=offset, sub=post.subr,
		fart=get_setting('Fart mode'))

@app.get("/viewmore/<pid>/<sort>/<offset>")
@limiter.limit(DEFAULT_RATELIMIT_SLOWER)
@auth_desired_with_logingate
def viewmore(v, pid, sort, offset):
	post = get_post(pid, v=v)
	if post.club and not (v and (v.paid_dues or v.id == post.author_id)): abort(403)
	try:
		offset = int(offset)
	except: abort(400)
	try: ids = set(int(x) for x in request.values.get("ids").split(','))
	except: abort(400)
	
	if v:
		# shadowban check is done in sort_objects
		# output is needed: see comments.py
		comments, output = get_comments_v_properties(v, True, None, Comment.parent_submission == pid, Comment.stickied == None, Comment.id.notin_(ids), Comment.level < 10)
		comments = comments.filter(Comment.level == 1)
		comments = sort_objects(sort, comments, Comment,
			include_shadowbanned=(v and v.can_see_shadowbanned))

		comments = [c[0] for c in comments.all()]
	else:
		comments = g.db.query(Comment).filter(
				Comment.parent_submission == pid,
				Comment.level == 1,
				Comment.stickied == None,
				Comment.id.notin_(ids)
			)

		comments = sort_objects(sort, comments, Comment,
			include_shadowbanned=False)
		
		comments = comments.offset(offset).all()

	comments2 = []
	count = 0
	if post.created_utc > 1638672040: # TODO: migrate old comments to use top_comment_id
		for comment in comments:
			comments2.append(comment)
			ids.add(comment.id)
			count += g.db.query(Comment).filter_by(parent_submission=post.id, top_comment_id=comment.id).count() + 1
			if count > 100: break
	else:
		for comment in comments:
			comments2.append(comment)
			ids.add(comment.id)
			count += g.db.query(Comment).filter_by(parent_submission=post.id, parent_comment_id=comment.id).count() + 1
			if count > 20: break
	
	if len(comments) == len(comments2): offset = 0
	else: offset += 1
	comments = comments2

	return render_template("comments.html", v=v, comments=comments, p=post, ids=list(ids), render_replies=True, pid=pid, sort=sort, offset=offset)


@app.get("/morecomments/<cid>")
@limiter.limit(DEFAULT_RATELIMIT_SLOWER)
@auth_desired_with_logingate
def morecomments(v, cid):
	try: cid = int(cid)
	except: abort(404)

	tcid = g.db.query(Comment.top_comment_id).filter_by(id=cid).one_or_none()[0]

	if v:
		# shadowban check is done in sort_objects i think
		# output is needed: see comments.py
		comments, output = get_comments_v_properties(v, True, lambda c:bool(c.parent_comment_id == int(cid)), Comment.top_comment_id == tcid, Comment.level > 9)
		comments = output
	else:
		c = get_comment(cid)
		comments = c.replies(sort=request.values.get('sort'), v=v, db=g.db)

	if comments: p = comments[0].post
	else: p = None
	
	return render_template("comments.html", v=v, comments=comments, p=p, render_replies=True)

@app.post("/edit_post/<pid>")
@limiter.limit("1/second;10/minute;100/hour;200/day")
@ratelimit_user("1/second;10/minute;100/hour;200/day")
@is_not_permabanned
def edit_post(pid, v):
	p = get_post(pid)
	if v.id != p.author_id and v.admin_level < PERMS['POST_EDITING']:
		abort(403)

	# Disable edits on things older than 1wk unless it's a draft or editor is a jannie
	if (time.time() - p.created_utc > 7*24*60*60 and not p.private
			and not v.admin_level >= PERMS['POST_EDITING']):
		abort(403, "You can't edit posts older than 1 week!")

	title = sanitize_raw_title(request.values.get("title", ""))
	body = sanitize_raw_body(request.values.get("body", ""), True)

	if v.id == p.author_id:
		if v.longpost and (len(body) < 280 or ' [](' in body or body.startswith('[](')):
			abort(403, "You have to type more than 280 characters!")
		elif v.bird and len(body) > 140:
			abort(403, "You have to type less than 140 characters!")

	if not title:
		abort(400, "Please enter a better title.")
	if title != p.title:
		torture = (v.agendaposter and not v.marseyawarded and p.sub != 'chudrama' and v.id == p.author_id)

		title_html = filter_emojis_only(title, golden=False, torture=torture)

		if v.id == p.author_id and v.marseyawarded and not marseyaward_title_regex.fullmatch(title_html):
			abort(403, "You can only type marseys!")

		p.title = title
		p.title_html = title_html

	body += process_files(request.files, v)
	body = body.strip()[:POST_BODY_LENGTH_LIMIT] # process_files() may be adding stuff to the body

	if body != p.body:
		if v and v.admin_level >= PERMS['POST_BETS']:
			for i in bet_regex.finditer(body):
				body = body.replace(i.group(0), "")
				body_html = filter_emojis_only(i.group(1))
				if len(body_html) > 500: abort(400, "Bet option too long!")
				bet = SubmissionOption(
					submission_id=p.id,
					body_html=body_html,
					exclusive = 2
				)
				g.db.add(bet)

		for i in poll_regex.finditer(body):
			body = body.replace(i.group(0), "")
			body_html = filter_emojis_only(i.group(1))
			if len(body_html) > 500: abort(400, "Poll option too long!")
			option = SubmissionOption(
				submission_id=p.id,
				body_html=body_html,
				exclusive = 0
			)
			g.db.add(option)

		for i in choice_regex.finditer(body):
			body = body.replace(i.group(0), "")
			body_html = filter_emojis_only(i.group(1))
			if len(body_html) > 500: abort(400, "Poll option too long!")
			choice = SubmissionOption(
				submission_id=p.id,
				body_html=body_html,
				exclusive = 1
			)
			g.db.add(choice)

		torture = (v.agendaposter and not v.marseyawarded and p.sub != 'chudrama' and v.id == p.author_id)

		body_html = sanitize(body, golden=False, limit_pings=100, showmore=False, torture=torture)

		if v.id == p.author_id and v.marseyawarded and marseyaward_body_regex.search(body_html):
			abort(403, "You can only type marseys!")


		p.body = body

		for text in [p.body, p.title, p.url]:
			if not execute_blackjack(v, p, text, 'submission'): break

		if len(body_html) > POST_BODY_HTML_LENGTH_LIMIT: 
			abort(400, f"Submission body_html too long! (max {POST_BODY_HTML_LENGTH_LIMIT} characters)")

		p.body_html = body_html

		if v.id == p.author_id and v.agendaposter and not v.marseyawarded and AGENDAPOSTER_PHRASE not in f'{p.body}{p.title}'.lower() and p.sub != 'chudrama':
			abort(403, f'You have to include "{AGENDAPOSTER_PHRASE}" in your post!')


	if not p.private and not p.ghost:
		notify_users = NOTIFY_USERS(f'{p.title} {p.body}', v)
		if notify_users:
			cid = notif_comment2(p)
			for x in notify_users:
				add_notif(cid, x)

	if v.id == p.author_id:
		if int(time.time()) - p.created_utc > 60 * 3: p.edited_utc = int(time.time())
		g.db.add(p)
	else:
		ma=ModAction(
			kind="edit_post",
			user_id=v.id,
			target_submission_id=p.id
		)
		g.db.add(ma)


	return redirect(p.permalink)


def thumbnail_thread(pid:int, vid:int):
	db = db_session()
	def expand_url(post_url, fragment_url):
		if fragment_url.startswith("https://"):
			return fragment_url
		elif fragment_url.startswith("https://"):
			return f"https://{fragment_url.split('https://')[1]}"
		elif fragment_url.startswith('//'):
			return f"https:{fragment_url}"
		elif fragment_url.startswith('/') and '\\' not in fragment_url:
			parsed_url = urlparse(post_url)
			return f"https://{parsed_url.netloc}{fragment_url}"
		else:
			return f"{post_url}/{fragment_url}"

	post = db.get(Submission, pid)
	
	if not post or not post.url:
		time.sleep(5)
		post = db.get(Submission, pid)

	if not post or not post.url: return
	
	fetch_url = post.url

	if fetch_url.startswith('/') and '\\' not in fetch_url:
		fetch_url = f"{SITE_FULL}{fetch_url}"

	headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.72 Safari/537.36"}

	try:
		x=requests.get(fetch_url, headers=headers, timeout=5, proxies=proxies)
	except:
		db.close()
		return

	if x.status_code != 200:
		db.close()
		return

	if x.headers.get("Content-Type","").startswith("text/html"):
		soup=BeautifulSoup(x.content, 'lxml')

		thumb_candidate_urls=[]

		meta_tags = [
			"drama:thumbnail",
			"twitter:image",
			"og:image",
			"thumbnail"
			]

		for tag_name in meta_tags:
			

			tag = soup.find(
				'meta', 
				attrs={
					"name": tag_name, 
					"content": True
					}
				)
			if not tag:
				tag = soup.find(
					'meta',
					attrs={
						'property': tag_name,
						'content': True
						}
					)
			if tag:
				thumb_candidate_urls.append(expand_url(post.url, tag['content']))

		for tag in soup.find_all("img", attrs={'src':True}):
			thumb_candidate_urls.append(expand_url(post.url, tag['src']))


		for url in thumb_candidate_urls:
			try:
				image_req=requests.get(url, headers=headers, timeout=5, proxies=proxies)
			except:
				continue

			if image_req.status_code >= 400:
				continue

			if not image_req.headers.get("Content-Type","").startswith("image/"):
				continue

			if image_req.headers.get("Content-Type","").startswith("image/svg"):
				continue

			with Image.open(BytesIO(image_req.content)) as i:
				if i.width < 30 or i.height < 30:
					continue
			break
		else:
			db.close()
			return

	elif x.headers.get("Content-Type","").startswith("image/"):
		image_req=x
		with Image.open(BytesIO(x.content)) as i:
			size = len(i.fp.read())
			if size > 8 * 1024 * 1024:
				db.close()
				return

	else:
		db.close()
		return

	name = f'/images/{time.time()}'.replace('.','') + '.webp'

	with open(name, "wb") as file:
		for chunk in image_req.iter_content(1024):
			file.write(chunk)

	v = db.get(User, vid)
	url = process_image(name, v, resize=100, uploader_id=post.author_id, db=db)
	if url:
		post.thumburl = url
		db.add(post)
		db.commit()
	db.close()
	stdout.flush()
	return


@app.post("/is_repost")
def is_repost():
	not_a_repost = {'permalink': ''}
	if not FEATURES['REPOST_DETECTION']:
		return not_a_repost

	url = request.values.get('url')
	if not url or len(url) < MIN_REPOST_CHECK_URL_LENGTH: abort(400)

	url = normalize_url(url)
	parsed_url = urlparse(url)

	domain = parsed_url.netloc
	if domain in ('old.reddit.com','twitter.com','instagram.com','tiktok.com') and '/search' not in url:
		new_url = ParseResult(scheme="https",
				netloc=parsed_url.netloc,
				path=parsed_url.path,
				params=parsed_url.params,
				query=None,
				fragment=parsed_url.fragment)
	else:
		qd = parse_qs(parsed_url.query, keep_blank_values=True)
		filtered = {k: val for k, val in qd.items() if not k.startswith('utm_') and not k.startswith('ref_')}

		new_url = ParseResult(scheme="https",
							netloc=parsed_url.netloc,
							path=parsed_url.path,
							params=parsed_url.params,
							query=urlencode(filtered, doseq=True),
							fragment=parsed_url.fragment)
	
	url = urlunparse(new_url)
	url = url.rstrip('/')

	search_url = url.replace('%', '').replace('\\', '').replace('_', '\_').strip()
	repost = g.db.query(Submission).filter(
		Submission.url.ilike(search_url),
		Submission.deleted_utc == 0,
		Submission.is_banned == False
	).first()
	if repost: return {'permalink': repost.permalink}
	else: return not_a_repost

@app.post("/submit")
@app.post("/h/<sub>/submit")
@limiter.limit(POST_RATE_LIMIT)
@limiter.limit(POST_RATE_LIMIT, key_func=lambda:f'{SITE}-{session.get("lo_user")}')
@auth_required
def submit_post(v, sub=None):

	url = request.values.get("url", "").strip()

	if '\\' in url: abort(400)

	title = sanitize_raw_title(request.values.get("title", ""))
	body = sanitize_raw_body(request.values.get("body", ""), True)

	def error(error):
		if g.is_api_or_xhr: abort(400, error)
	
		SUBS = [x[0] for x in g.db.query(Sub.name).order_by(Sub.name).all()]
		return render_template("submit.html", SUBS=SUBS, v=v, error=error, title=title, url=url, body=body), 400

	if not title:
		return error("Please enter a better title.")
	torture = (v.agendaposter and not v.marseyawarded and sub != 'chudrama')
	title_html = filter_emojis_only(title, graceful=True, count_marseys=True, torture=torture)
	if v.marseyawarded and not marseyaward_title_regex.fullmatch(title_html):
		return error("You can only type marseys!")
	if len(title_html) > POST_TITLE_HTML_LENGTH_LIMIT: 
		return error("Rendered title is too big!")

	sub = request.values.get("sub", "").lower().replace('/h/','').strip()

	if sub == 'changelog' and not v.admin_level >= PERMS['POST_TO_CHANGELOG']:
		# we also allow 'code contributor' badgeholders to post to the changelog hole
		allowed = g.db.query(Badge.user_id).filter_by(badge_id=3).all()
		allowed = [x[0] for x in allowed]
		if v.id not in allowed: return error("You don't have sufficient permissions to post in /h/changelog")

	if sub in ('furry','vampire','racist','femboy') and not v.client and not v.house.lower().startswith(sub):
		return error(f"You need to be a member of House {sub.capitalize()} to post in /h/{sub}")

	if sub and sub != 'none':
		sname = sub.strip().lower()
		sub = g.db.query(Sub.name).filter_by(name=sname).one_or_none()
		if not sub: return error(f"/h/{sname} not found!")
		sub = sub[0]
		if v.exiled_from(sub): return error(f"You're exiled from /h/{sub}")
	else: sub = None

	if not sub and HOLE_REQUIRED:
		return error(f"You must choose a {HOLE_NAME} for your post!")

	if v.is_suspended: return error("You can't perform this action while banned.")

	if v.longpost and (len(body) < 280 or ' [](' in body or body.startswith('[](')):
		return error("You have to type more than 280 characters!")
	elif v.bird and len(body) > 140:
		return error("You have to type less than 140 characters!")


	embed = None

	if url:
		url = normalize_url(url)
		parsed_url = urlparse(url)

		domain = parsed_url.netloc
		if domain in ('old.reddit.com','twitter.com','instagram.com','tiktok.com') and '/search' not in url:
			new_url = ParseResult(scheme="https",
					netloc=parsed_url.netloc,
					path=parsed_url.path,
					params=parsed_url.params,
					query=None,
					fragment=parsed_url.fragment)
		else:
			qd = parse_qs(parsed_url.query, keep_blank_values=True)
			filtered = {k: val for k, val in qd.items() if not k.startswith('utm_') and not k.startswith('ref_')}

			new_url = ParseResult(scheme="https",
								netloc=parsed_url.netloc,
								path=parsed_url.path,
								params=parsed_url.params,
								query=urlencode(filtered, doseq=True),
								fragment=parsed_url.fragment)
		
		url = urlunparse(new_url)

		url = url.rstrip('/')

		search_url = url.replace('%', '').replace('\\', '').replace('_', '\_').strip()
		repost = g.db.query(Submission).filter(
			Submission.url.ilike(search_url),
			Submission.deleted_utc == 0,
			Submission.is_banned == False
		).first()
		if repost and FEATURES['REPOST_DETECTION'] and not v.admin_level >= PERMS['POST_BYPASS_REPOST_CHECKING']:
			return redirect(repost.permalink)

		y = tldextract.extract(url).registered_domain + parsed_url.path
		y = y.lower()
		banned_domains = g.db.query(BannedDomain).all()
		for x in banned_domains:
			if y.startswith(x.domain):
				return error(f'Remove the banned link "{x.domain}" and try again!<br>Reason for link ban: "{x.reason}"')

		if "twitter.com" == domain:
			try:
				embed = requests.get("https://publish.twitter.com/oembed", params={"url":url, "omit_script":"t"}, timeout=5).json()["html"]
				embed = embed.replace('<a href', '<a rel="nofollow noopener" href')
			except: pass
		elif url.startswith('https://youtube.com/watch?v='):
			url = unquote(url).replace('?t', '&t')
			yt_id = url.split('https://youtube.com/watch?v=')[1].split('&')[0].split('%')[0]

			if yt_id_regex.fullmatch(yt_id):
				params = parse_qs(urlparse(url).query, keep_blank_values=True)
				t = params.get('t', params.get('start', [0]))[0]
				if isinstance(t, str): t = t.replace('s','')

				embed = f'<lite-youtube videoid="{yt_id}" params="autoplay=1&modestbranding=1'
				if t:
					try: embed += f'&start={int(t)}'
					except: pass
				embed += '"></lite-youtube>'

		elif SITE in domain and "/post/" in url and "context" not in url and url.count('/') < 6:
			id = url.split("/post/")[1]
			if "/" in id: id = id.split("/")[0]
			embed = str(int(id))


	if not url and not body and not request.files.get("file") and not request.files.get("file-url"):
		return error("Please enter a url or some text.")

	if not IS_LOCALHOST: 
		dup = g.db.query(Submission).filter(
			Submission.author_id == v.id,
			Submission.deleted_utc == 0,
			Submission.title == title,
			Submission.url == url,
			Submission.body == body
		).one_or_none()
		if dup: return redirect(dup.permalink)

	if not execute_antispam_submission_check(title, v, url):
		return redirect("/notifications")

	if len(url) > 2048:
		return error("There's a 2048 character limit for URLs.")

	bets = []
	if v and v.admin_level >= PERMS['POST_BETS']:
		for i in bet_regex.finditer(body):
			bets.append(i.group(1))
			body = body.replace(i.group(0), "")

	options = []
	for i in poll_regex.finditer(body):
		options.append(i.group(1))
		body = body.replace(i.group(0), "")

	choices = []
	for i in choice_regex.finditer(body):
		choices.append(i.group(1))
		body = body.replace(i.group(0), "")

	body += process_files(request.files, v)
	body = body.strip()[:POST_BODY_LENGTH_LIMIT] # process_files() adds content to the body, so we need to re-strip

	torture = (v.agendaposter and not v.marseyawarded and sub != 'chudrama')

	body_html = sanitize(body, count_marseys=True, limit_pings=100, showmore=False, torture=torture)

	if v.marseyawarded and marseyaward_body_regex.search(body_html):
		return error("You can only type marseys!")

	if len(body_html) > POST_BODY_HTML_LENGTH_LIMIT: return error(f"Submission body_html too long! (max {POST_BODY_HTML_LENGTH_LIMIT} characters)")

	flag_notify = (request.values.get("notify", "on") == "on")
	flag_new = request.values.get("new", False, bool)
	flag_over_18 = request.values.get("over_18", False, bool)
	flag_private = request.values.get("private", False, bool)
	flag_club = (request.values.get("club", False, bool) and FEATURES['COUNTRY_CLUB'])
	flag_ghost = request.values.get("ghost", False, bool) and v.can_post_in_ghost_threads

	if embed and len(embed) > 1500: embed = None
	if embed: embed = embed.strip()

	if url and url.startswith(SITE_FULL):
		url = url.split(SITE_FULL)[1]

	post = Submission(
		private=flag_private,
		notify=flag_notify,
		club=flag_club,
		author_id=v.id,
		over_18=flag_over_18,
		new=flag_new,
		app_id=v.client.application.id if v.client else None,
		is_bot=(v.client is not None),
		url=url,
		body=body,
		body_html=body_html,
		embed_url=embed,
		title=title,
		title_html=title_html,
		sub=sub,
		ghost=flag_ghost
	)

	g.db.add(post)
	g.db.flush()

	for text in [post.body, post.title, post.url]:
		if not execute_blackjack(v, post, text, 'submission'): break

	if v and v.admin_level >= PERMS['POST_BETS']:
		for bet in bets:
			body_html = filter_emojis_only(bet)
			if len(body_html) > 500: abort(400, "Bet option too long!")
			bet = SubmissionOption(
				submission_id=post.id,
				body_html=body_html,
				exclusive=2
			)
			g.db.add(bet)

	for option in options:
		body_html = filter_emojis_only(option)
		if len(body_html) > 500: abort(400, "Poll option too long!")
		option = SubmissionOption(
			submission_id=post.id,
			body_html=body_html,
			exclusive=0
		)
		g.db.add(option)

	for choice in choices:
		body_html = filter_emojis_only(choice)
		if len(body_html) > 500: abort(400, "Poll option too long!")
		choice = SubmissionOption(
			submission_id=post.id,
			body_html=body_html,
			exclusive=1
		)
		g.db.add(choice)

	vote = Vote(user_id=v.id,
				vote_type=1,
				submission_id=post.id
				)
	g.db.add(vote)
	
	if request.files.get('file-url') and not g.is_tor:
		file = request.files['file-url']

		if file.content_type.startswith('image/'):
			name = f'/images/{time.time()}'.replace('.','') + '.webp'
			file.save(name)
			post.url = process_image(name, v)

			name2 = name.replace('.webp', 'r.webp')
			copyfile(name, name2)
			post.thumburl = process_image(name2, v, resize=100)
		elif file.content_type.startswith('video/'):
			post.url = process_video(file, v)
		elif file.content_type.startswith('audio/'):
			post.url = process_audio(file, v)
		else:
			abort(415)
		
	if not post.thumburl and post.url:
		gevent.spawn(thumbnail_thread, post.id, v.id)

	if not post.private and not post.ghost:
		notify_users = NOTIFY_USERS(f'{title} {body}', v)

		if notify_users:
			cid = notif_comment2(post)
			for x in notify_users:
				add_notif(cid, x)

	if v.agendaposter and not v.marseyawarded and AGENDAPOSTER_PHRASE not in f'{post.body}{post.title}'.lower() and sub != 'chudrama':
		post.is_banned = True
		post.ban_reason = "AutoJanny"

		body = AGENDAPOSTER_MSG.format(username=v.username, type='post', AGENDAPOSTER_PHRASE=AGENDAPOSTER_PHRASE)

		body_jannied_html = AGENDAPOSTER_MSG_HTML.format(id=v.id, username=v.username, type='post', AGENDAPOSTER_PHRASE=AGENDAPOSTER_PHRASE)


		c_jannied = Comment(author_id=AUTOJANNY_ID,
			parent_submission=post.id,
			level=1,
			over_18=False,
			is_bot=True,
			app_id=None,
			stickied='AutoJanny',
			distinguish_level=6,
			body=body,
			body_html=body_jannied_html,
			ghost=post.ghost
		)

		g.db.add(c_jannied)
		g.db.flush()

		c_jannied.top_comment_id = c_jannied.id

		n = Notification(comment_id=c_jannied.id, user_id=v.id)
		g.db.add(n)



	if not post.private and not (post.sub and g.db.query(Exile.user_id).filter_by(user_id=SNAPPY_ID, sub=post.sub).one_or_none()):
		execute_snappy(post, v)




	v.post_count = g.db.query(Submission).filter_by(author_id=v.id, deleted_utc=0).count()
	g.db.add(v)

	execute_lawlz_actions(v, post)

	cache.delete_memoized(frontlist)
	cache.delete_memoized(userpagelisting)

	if post.sub == 'changelog' and not post.private:
		send_changelog_message(post.permalink)

	if not post.private and SITE == 'watchpeopledie.tv':
		send_wpd_message(post.permalink)

	g.db.commit()
	if v.client: return post.json(g.db)
	else:
		post.voted = 1
		if post.new or 'megathread' in post.title.lower(): sort = 'new'
		else: sort = v.defaultsortingcomments
		return render_template('submission.html', v=v, p=post, sort=sort, render_replies=True, offset=0, success=True, sub=post.subr)


@app.post("/delete_post/<pid>")
@limiter.limit(DEFAULT_RATELIMIT_SLOWER)
@auth_required
@ratelimit_user()
def delete_post_pid(pid, v):
	post = get_post(pid)
	if post.author_id != v.id: abort(403)

	# Temporary special logic by Carp request for events of 2022-10-10
	if SITE_NAME == 'rDrama' and post.author_id == 3161: abort(403)

	if not post.deleted_utc:
		post.deleted_utc = int(time.time())
		post.is_pinned = False
		post.stickied = None

		g.db.add(post)

		cache.delete_memoized(frontlist)
		cache.delete_memoized(userpagelisting)

		g.db.flush()
		v.post_count = g.db.query(Submission).filter_by(author_id=v.id, deleted_utc=0).count()
		g.db.add(v)

	return {"message": "Post deleted!"}

@app.post("/undelete_post/<pid>")
@limiter.limit(DEFAULT_RATELIMIT_SLOWER)
@auth_required
@ratelimit_user()
def undelete_post_pid(pid, v):
	post = get_post(pid)
	if post.author_id != v.id: abort(403)

	if post.deleted_utc:
		post.deleted_utc = 0
		g.db.add(post)

		cache.delete_memoized(frontlist)
		cache.delete_memoized(userpagelisting)

		g.db.flush()
		v.post_count = g.db.query(Submission).filter_by(author_id=v.id, deleted_utc=0).count()
		g.db.add(v)

	return {"message": "Post undeleted!"}


@app.post("/toggle_post_nsfw/<pid>")
@auth_required
def toggle_post_nsfw(pid, v):
	post = get_post(pid)

	if post.author_id != v.id and not v.admin_level >= PERMS['POST_COMMENT_MODERATION'] and not (post.sub and v.mods(post.sub)):
		abort(403)
		
	if post.over_18 and v.is_suspended_permanently:
		abort(403)

	post.over_18 = not post.over_18
	g.db.add(post)

	if post.author_id != v.id:
		if v.admin_level >= PERMS['POST_COMMENT_MODERATION']:
			ma = ModAction(
					kind = "set_nsfw" if post.over_18 else "unset_nsfw",
					user_id = v.id,
					target_submission_id = post.id,
				)
			g.db.add(ma)
		else:
			ma = SubAction(
					sub = post.sub,
					kind = "set_nsfw" if post.over_18 else "unset_nsfw",
					user_id = v.id,
					target_submission_id = post.id,
				)
			g.db.add(ma)

	if post.over_18: return {"message": "Post has been marked as +18!"}
	else: return {"message": "Post has been unmarked as +18!"}

@app.post("/save_post/<pid>")
@limiter.limit(DEFAULT_RATELIMIT_SLOWER)
@auth_required
@ratelimit_user()
def save_post(pid, v):

	post=get_post(pid)

	save = g.db.query(SaveRelationship).filter_by(user_id=v.id, submission_id=post.id).one_or_none()

	if not save:
		new_save=SaveRelationship(user_id=v.id, submission_id=post.id)
		g.db.add(new_save)

	return {"message": "Post saved!"}

@app.post("/unsave_post/<pid>")
@limiter.limit(DEFAULT_RATELIMIT_SLOWER)
@auth_required
@ratelimit_user()
def unsave_post(pid, v):

	post=get_post(pid)

	save = g.db.query(SaveRelationship).filter_by(user_id=v.id, submission_id=post.id).one_or_none()

	if save:
		g.db.delete(save)

	return {"message": "Post unsaved!"}

@app.post("/pin/<post_id>")
@auth_required
def pin_post(post_id, v):
	post = get_post(post_id)
	if post:
		if v.id != post.author_id: abort(403, "Only the post author can do that!")
		post.is_pinned = not post.is_pinned
		g.db.add(post)
		cache.delete_memoized(userpagelisting)
		if post.is_pinned: return {"message": "Post pinned!"}
		else: return {"message": "Post unpinned!"}
	return abort(404, "Post not found!")


extensions = IMAGE_FORMATS + VIDEO_FORMATS + AUDIO_FORMATS

@app.get("/submit/title")
@limiter.limit("3/minute")
@ratelimit_user("3/minute")
@auth_required
def get_post_title(v):
	url = request.values.get("url")
	if not url or '\\' in url: abort(400)
	url = url.strip()
	if not url.startswith('http'): abort(400)

	checking_url = url.lower().split('?')[0].split('%3F')[0]
	if any((checking_url.endswith(f'.{x}') for x in extensions)):
		abort(400)

	try: x = requests.get(url, headers=titleheaders, timeout=5, proxies=proxies)
	except: abort(400)
		
	content_type = x.headers.get("Content-Type")
	if not content_type or "text/html" not in content_type: abort(400)

	# no you can't just parse html with reeeeeeeegex
	match = html_title_regex.search(x.text)
	if match and match.lastindex >= 1:
		title = match.group(1)
	else: abort(400)

	return {"url": url, "title": title}
