import os
from shutil import copyfile

from sqlalchemy import func, nullslast
from files.helpers.media import process_files

import files.helpers.stats as statshelper
from files.classes.award import AWARDS
from files.classes.badges import Badge, BadgeDef
from files.classes.mod_logs import ModAction, ACTIONTYPES, ACTIONTYPES2
from files.classes.userblock import UserBlock
from files.helpers.actions import *
from files.helpers.alerts import *
from files.helpers.const import *
from files.routes.wrappers import *
from files.__main__ import app, cache, limiter


@app.get("/r/drama/comments/<id>/<title>")
@app.get("/r/Drama/comments/<id>/<title>")
def rdrama(id, title):
	id = ''.join(f'{x}/' for x in id)
	return redirect(f'/archives/drama/comments/{id}{title}.html')


@app.get("/marseys")
@auth_required
def marseys(v):
	if SITE == 'rdrama.net':
		marseys = g.db.query(Marsey, User).join(User, Marsey.author_id == User.id).filter(Marsey.submitter_id==None)
		sort = request.values.get("sort", "usage")
		if sort == "usage":
			marseys = marseys.order_by(Marsey.count.desc(), User.username).all()
		elif sort == "added":
			marseys = marseys.order_by(nullslast(Marsey.created_utc.desc()), User.username).all()
		else: # implied sort == "author"
			marseys = marseys.order_by(User.username, Marsey.count.desc()).all()

		original = os.listdir("/asset_submissions/marseys/original")
		for marsey, user in marseys:
			for x in IMAGE_FORMATS:
				if f'{marsey.name}.{x}' in original:
					marsey.og = f'{marsey.name}.{x}'
					break
	else:
		marseys = g.db.query(Marsey).filter(Marsey.submitter_id==None).order_by(Marsey.count.desc())

	return render_template("marseys.html", v=v, marseys=marseys)

@app.get("/marsey_list.json")
@cache.memoize(timeout=600)
def marsey_list():
	emojis = []

	# From database
	if EMOJI_MARSEYS:
		emojis = [{
			"name": emoji.name,
			"author": author if SITE == 'rdrama.net' or author == "anton-d" else None,
			# yikes, I don't really like this DB schema. Next time be better
			"tags": emoji.tags.split(" ") + [emoji.name[len("marsey"):] \
						if emoji.name.startswith("marsey") else emoji.name],
			"count": emoji.count,
			"class": "Marsey"
		} for emoji, author in g.db.query(Marsey, User.username).join(User, Marsey.author_id == User.id).filter(Marsey.submitter_id==None) \
			.order_by(Marsey.count.desc())]

	# Static shit
	for src in EMOJI_SRCS:
		with open(src, "r", encoding="utf-8") as f:
			emojis = emojis + json.load(f)

	return jsonify(emojis)

@app.get('/sidebar')
@auth_desired
def sidebar(v):
	return render_template('sidebar.html', v=v)


@app.get("/stats")
@auth_required
def participation_stats(v):
	if v.client: return stats_cached()
	return render_template("stats.html", v=v, title="Content Statistics", data=stats_cached())

@cache.memoize(timeout=86400)
def stats_cached():
	return statshelper.stats(SITE_NAME)

@app.get("/chart")
def chart():
	return redirect('/weekly_chart')

@app.get("/weekly_chart")
@auth_required
def weekly_chart(v):
	return send_file(statshelper.chart_path(kind="weekly", site=SITE))

@app.get("/daily_chart")
@auth_required
def daily_chart(v):
	return send_file(statshelper.chart_path(kind="daily", site=SITE))

@app.get("/patrons")
@app.get("/paypigs")
@admin_level_required(PERMS['VIEW_PATRONS'])
def patrons(v):
	if AEVANN_ID and v.id not in (AEVANN_ID, CARP_ID, SNAKES_ID): abort(404)

	users = g.db.query(User).filter(User.patron > 0).order_by(User.patron.desc(), User.id).all()

	return render_template("patrons.html", v=v, users=users, benefactor_def=AWARDS['benefactor'])

@app.get("/admins")
@app.get("/badmins")
@auth_required
def admins(v):
	if v.admin_level >= PERMS['VIEW_SORTED_ADMIN_LIST']:
		admins = g.db.query(User).filter(User.admin_level>1).order_by(User.truescore.desc()).all()
		admins += g.db.query(User).filter(User.admin_level==1).order_by(User.truescore.desc()).all()
	else: admins = g.db.query(User).filter(User.admin_level>0).order_by(User.truescore.desc()).all()
	return render_template("admins.html", v=v, admins=admins)


@app.get("/log")
@app.get("/modlog")
@auth_required
def log(v):

	try: page = max(int(request.values.get("page", 1)), 1)
	except: page = 1

	admin = request.values.get("admin")
	if admin: admin_id = get_id(admin)
	else: admin_id = 0

	kind = request.values.get("kind")

	if v and v.admin_level >= PERMS['USER_SHADOWBAN']: types = ACTIONTYPES
	else: types = ACTIONTYPES2

	if kind and kind not in types:
		kind = None
		actions = []
	else:
		actions = g.db.query(ModAction)
		if not (v and v.admin_level >= PERMS['USER_SHADOWBAN']): 
			actions = actions.filter(ModAction.kind.notin_([
				"shadowban","unshadowban",
				"mod_mute_user","mod_unmute_user",
				"link_accounts","delink_accounts",
				]))

		if admin_id:
			actions = actions.filter_by(user_id=admin_id)
			kinds = set([x.kind for x in actions])
			kinds.add(kind)
			types2 = {}
			for k,val in types.items():
				if k in kinds: types2[k] = val
			types = types2
		if kind: actions = actions.filter_by(kind=kind)

		actions = actions.order_by(ModAction.id.desc()).offset(PAGE_SIZE*(page-1)).limit(PAGE_SIZE+1).all()
	
	next_exists=len(actions) > PAGE_SIZE
	actions=actions[:PAGE_SIZE]
	admins = [x[0] for x in g.db.query(User.username).filter(User.admin_level >= PERMS['ADMIN_MOP_VISIBLE']).order_by(User.username).all()]

	return render_template("log.html", v=v, admins=admins, types=types, admin=admin, type=kind, actions=actions, next_exists=next_exists, page=page, single_user_url='admin')

@app.get("/log/<id>")
@auth_required
def log_item(id, v):
	try: id = int(id)
	except: abort(404)

	action=g.db.get(ModAction, id)

	if not action: abort(404)

	admins = [x[0] for x in g.db.query(User.username).filter(User.admin_level >= PERMS['ADMIN_MOP_VISIBLE']).all()]

	if v and v.admin_level >= PERMS['USER_SHADOWBAN']: types = ACTIONTYPES
	else: types = ACTIONTYPES2

	return render_template("log.html", v=v, actions=[action], next_exists=False, page=1, action=action, admins=admins, types=types, single_user_url='admin')

@app.get("/directory")
@auth_required
def static_megathread_index(v):
	return render_template("megathread_index.html", v=v)

@app.get("/api")
@auth_required
def api(v):
	return render_template("api.html", v=v)

@app.get("/contact")
@app.get("/contactus")
@app.get("/contact_us")
@app.get("/press")
@app.get("/media")
@auth_desired
def contact(v):
	return render_template("contact.html", v=v)

@app.post("/send_admin")
@limiter.limit("1/second;1/2 minutes;10/day")
@limiter.limit("1/second;1/2 minutes;10/day", key_func=lambda:f'{SITE}-{session.get("lo_user")}')
@auth_required
def submit_contact(v):
	body = request.values.get("message")
	if not body: abort(400)

	if v.is_muted:
		abort(403)

	body = f'This message has been sent automatically to all admins via [/contact](/contact)\n\nMessage:\n\n' + body
	body += process_files(request.files, v)
	body = body.strip()
	body_html = sanitize(body)

	execute_antispam_duplicate_comment_check(v, body_html)

	new_comment = Comment(author_id=v.id,
						parent_submission=None,
						level=1,
						body_html=body_html,
						sentto=2
						)
	g.db.add(new_comment)
	g.db.flush()
	execute_blackjack(v, new_comment, new_comment.body_html, 'modmail')
	new_comment.top_comment_id = new_comment.id
	
	admins = g.db.query(User).filter(User.admin_level >= PERMS['NOTIFICATIONS_MODMAIL'])
	if SITE == 'watchpeopledie.tv':
		admins = admins.filter(User.id != AEVANN_ID)

	for admin in admins.all():
		notif = Notification(comment_id=new_comment.id, user_id=admin.id)
		g.db.add(notif)



	return render_template("contact.html", v=v, msg="Your message has been sent to the admins!")

@app.get("/watchparty")
@is_not_permabanned
def chat_watchparty(v):
	return render_template("chat_watchparty.html", v=v)

@app.get('/archives')
def archivesindex():
	return redirect("/archives/index.html")

@app.get('/archives/<path:path>')
def archives(path):
	resp = make_response(send_from_directory('/archives', path))
	if request.path.endswith('.css'): resp.headers.add("Content-Type", "text/css")
	return resp

def static_file(dir:str, path:str, should_cache:bool, is_webp:bool) -> Response:
	resp = make_response(send_from_directory(dir, path))
	if should_cache:
		resp.headers.remove("Cache-Control")
		resp.headers.add("Cache-Control", "public, max-age=3153600")
	if is_webp:
		resp.headers.remove("Content-Type")
		resp.headers.add("Content-Type", "image/webp")
	return resp

@app.get('/e/<emoji>')
@limiter.exempt
def emoji(emoji):
	if not emoji.endswith('.webp'): abort(404)
	return static_file('assets/images/emojis', emoji, True, True)

@app.get('/i/<path:path>')
@limiter.exempt
def image(path):
	is_webp = path.endswith('.webp')
	return static_file('assets/images', path, is_webp or path.endswith('.gif') or path.endswith('.ttf') or path.endswith('.woff2'), is_webp)

@app.get('/assets/<path:path>')
@app.get('/static/assets/<path:path>')
@limiter.exempt
def static_service(path):
	is_webp = path.endswith('.webp')
	return static_file('assets', path, is_webp or path.endswith('.gif') or path.endswith('.ttf') or path.endswith('.woff2'), is_webp)

### BEGIN FALLBACK ASSET SERVING
# In production, we have nginx serve these locations now.
# These routes stay for local testing. Requests don't reach them on prod.

@app.get('/images/<path>')
@app.get('/hostedimages/<path>')
@app.get("/static/images/<path>")
@limiter.exempt
def images(path):
	return static_file('/images', path, True, True)

@app.get('/videos/<path>')
@limiter.exempt
def videos(path):
	return static_file('/videos', path, True, False)

@app.get('/audio/<path>')
@limiter.exempt
def audio(path):
	return static_file('/audio', path, True, False)

### END FALLBACK ASSET SERVING

@app.get("/robots.txt")
def robots_txt():
	return send_file("assets/robots.txt")

no = (21,22,23,24,25,26,27)

@cache.memoize(timeout=3600)
def badge_list(site):
	badges = g.db.query(BadgeDef).filter(BadgeDef.id.notin_(no)).order_by(BadgeDef.id).all()
	counts_raw = g.db.query(Badge.badge_id, func.count()).group_by(Badge.badge_id).all()
	users = g.db.query(User).count()

	counts = {}
	for c in counts_raw:
		counts[c[0]] = (c[1], float(c[1]) * 100 / max(users, 1))
	
	return badges, counts

@app.get("/badges")
@feature_required('BADGES')
@auth_required
def badges(v):
	badges, counts = badge_list(SITE)
	return render_template("badges.html", v=v, badges=badges, counts=counts)

@app.get("/blocks")
@admin_level_required(PERMS['USER_BLOCKS_VISIBLE'])
def blocks(v):
	blocks=g.db.query(UserBlock).all()
	users = []
	targets = []
	for x in blocks:
		acc_user = get_account(x.user_id)
		acc_tgt = get_account(x.target_id)
		if acc_user.shadowbanned or acc_tgt.shadowbanned: continue
		users.append(acc_user)
		targets.append(acc_tgt)

	return render_template("blocks.html", v=v, users=users, targets=targets)

@app.get("/banned")
@auth_required
def banned(v):
	users = g.db.query(User).filter(User.is_banned > 0, User.unban_utc == 0)
	if not v.can_see_shadowbanned:
		users = users.filter(User.shadowbanned == None)
	users = users.all()
	return render_template("banned.html", v=v, users=users)

@app.get("/formatting")
@auth_required
def formatting(v):
	return render_template("formatting.html", v=v)

@app.get("/service-worker.js")
def serviceworker():
	with open("files/assets/js/service-worker.js", "r", encoding="utf-8") as f:
		return Response(f.read(), mimetype='application/javascript')

@app.post("/dismiss_mobile_tip")
def dismiss_mobile_tip():
	session["tooltip_last_dismissed"] = int(time.time())
	return "", 204

@app.get("/transfers/<id>")
@auth_required
def transfers_id(id, v):

	try: id = int(id)
	except: abort(404)

	transfer = g.db.get(Comment, id)

	if not transfer: abort(404)

	return render_template("transfers.html", v=v, page=1, comments=[transfer], standalone=True, next_exists=False)

@app.get("/transfers")
@auth_required
def transfers(v):

	comments = g.db.query(Comment).filter(Comment.author_id == AUTOJANNY_ID, Comment.parent_submission == None, Comment.body_html.like("%</a> has transferred %")).order_by(Comment.id.desc())

	try: page = max(int(request.values.get("page", 1)), 1)
	except: page = 1

	comments = comments.offset(PAGE_SIZE * (page - 1)).limit(PAGE_SIZE + 1).all()
	next_exists = len(comments) > PAGE_SIZE
	comments = comments[:PAGE_SIZE]

	if v.client:
		return {"data": [x.json(g.db) for x in comments]}
	else:
		return render_template("transfers.html", v=v, page=page, comments=comments, standalone=True, next_exists=next_exists)


if not os.path.exists(f'files/templates/donate_{SITE_NAME}.html'):
	copyfile(f'files/templates/donate_rDrama.html', f'files/templates/donate_{SITE_NAME}.html')

@app.get('/donate')
@auth_desired_with_logingate
def donate(v):
	return render_template(f'donate_{SITE_NAME}.html', v=v)
