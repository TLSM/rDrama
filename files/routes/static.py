from files.mail import *
from files.__main__ import app, limiter, mail
from files.helpers.alerts import *
from files.helpers.const import *
from files.classes.award import AWARDS
from sqlalchemy import func
import os
from files.classes.mod_logs import ACTIONTYPES, ACTIONTYPES2
from files.classes.badges import BadgeDef
import files.helpers.stats as statshelper

@app.get("/r/drama/comments/<id>/<title>")
@app.get("/r/Drama/comments/<id>/<title>")
def rdrama(id, title):
	id = ''.join(f'{x}/' for x in id)
	return redirect(f'/archives/drama/comments/{id}{title}.html')


@app.get("/marseys")
@auth_required
def marseys(v):
	if SITE_NAME == 'rDrama':
		marseys = g.db.query(Marsey, User).join(User)
		sort = request.values.get("sort", "usage")
		if sort == "usage": marseys = marseys.order_by(Marsey.count.desc(), User.username)
		else: marseys = marseys.order_by(User.username, Marsey.count.desc())
	else:
		marseys = g.db.query(Marsey).order_by(Marsey.count.desc())
	return render_template("marseys.html", v=v, marseys=marseys)

@app.get("/marsey_list.json")
@cache.memoize(timeout=600)
def marsey_list():
	emojis = []

	# From database
	if EMOJI_MARSEYS:
		emojis = [{
			"name": emoji.name,
			"author": author if SITE_NAME == 'rDrama' or author == "anton-d" else None,
			# yikes, I don't really like this DB schema. Next time be better
			"tags": emoji.tags.split(" ") + [emoji.name[len("marsey"):] \
						if emoji.name.startswith("marsey") else emoji.name],
			"count": emoji.count,
			"class": "Marsey"
		} for emoji, author in g.db.query(Marsey, User.username).join(User) \
			.order_by(Marsey.count.desc())]

	# Static shit
	for src in EMOJI_SRCS:
		with open(src, "r", encoding="utf-8") as f:
			emojis = emojis + json.load(f)

	return jsonify(emojis)

@app.get('/rules')
@app.get('/sidebar')
@app.get('/logged_out/rules')
@app.get('/logged_out/sidebar')
@auth_desired
def sidebar(v):
	if not v and not request.path.startswith('/logged_out'): return redirect(f"/logged_out{request.full_path}")
	if v and request.path.startswith('/logged_out'): return redirect(request.full_path.replace('/logged_out',''))

	return render_template('sidebar.html', v=v)


@app.get("/stats")
@auth_required
def participation_stats(v):
	return render_template("admin/content_stats.html", 
		v=v, title="Content Statistics", data=stats_cached())

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
@admin_level_required(3)
def patrons(v):
	users = g.db.query(User).filter(User.patron > 0).order_by(User.patron.desc(), User.id).all()

	return render_template("patrons.html", v=v, users=users)

@app.get("/admins")
@app.get("/badmins")
@auth_required
def admins(v):
	if v and v.admin_level > 2:
		admins = g.db.query(User).filter(User.admin_level>1).order_by(User.truecoins.desc()).all()
		admins += g.db.query(User).filter(User.admin_level==1).order_by(User.truecoins.desc()).all()
	else: admins = g.db.query(User).filter(User.admin_level>0).order_by(User.truecoins.desc()).all()
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

	if v and v.admin_level > 1: types = ACTIONTYPES
	else: types = ACTIONTYPES2

	if kind and kind not in types:
		kind = None
		actions = []
	else:
		actions = g.db.query(ModAction)
		if not (v and v.admin_level >= 2): 
			actions = actions.filter(ModAction.kind.notin_(["shadowban","unshadowban"]))

		if admin_id:
			actions = actions.filter_by(user_id=admin_id)
			kinds = set([x.kind for x in actions])
			types2 = {}
			for k,val in types.items():
				if k in kinds: types2[k] = val
			types = types2
		if kind: actions = actions.filter_by(kind=kind)

		actions = actions.order_by(ModAction.id.desc()).offset(25*(page-1)).limit(26).all()
	
	next_exists=len(actions)>25
	actions=actions[:25]
	admins = [x[0] for x in g.db.query(User.username).filter(User.admin_level >= 2).order_by(User.username).all()]

	return render_template("log.html", v=v, admins=admins, types=types, admin=admin, type=kind, actions=actions, next_exists=next_exists, page=page)

@app.get("/log/<id>")
@auth_required
def log_item(id, v):

	try: id = int(id)
	except: abort(404)

	action=g.db.get(ModAction, id)

	if not action: abort(404)

	admins = [x[0] for x in g.db.query(User.username).filter(User.admin_level > 1).all()]

	if v and v.admin_level > 1: types = ACTIONTYPES
	else: types = ACTIONTYPES2

	return render_template("log.html", v=v, actions=[action], next_exists=False, page=1, action=action, admins=admins, types=types)

@app.get("/directory")
@auth_desired
def static_megathread_index(v):
	return render_template("megathread_index.html", v=v)

@app.get("/api")
@auth_required
def api(v):
	return render_template("api.html", v=v)

@app.get("/contact")
@app.get("/press")
@app.get("/media")
@auth_required
def contact(v):

	return render_template("contact.html", v=v)

@app.post("/send_admin")
@limiter.limit("1/second;2/minute;6/hour;10/day")
@limiter.limit("1/second;2/minute;6/hour;10/day", key_func=lambda:f'{request.host}-{session.get("lo_user")}')
@auth_required
def submit_contact(v):
	body = request.values.get("message")
	if not body: abort(400)

	body = f'This message has been sent automatically to all admins via [/contact](/contact)\n\nMessage:\n\n' + body

	body += process_files()

	body = body.strip()
	
	body_html = sanitize(body)

	new_comment = Comment(author_id=v.id,
						  parent_submission=None,
						  level=1,
						  body_html=body_html,
						  sentto=2
						  )
	g.db.add(new_comment)
	g.db.flush()
	new_comment.top_comment_id = new_comment.id
	
	for admin in g.db.query(User).filter(User.admin_level > 2).all():
		notif = Notification(comment_id=new_comment.id, user_id=admin.id)
		g.db.add(notif)



	return render_template("contact.html", v=v, msg="Your message has been sent.")

@app.get('/archives')
def archivesindex():
	return redirect("/archives/index.html")

@app.get('/archives/<path:path>')
def archives(path):
	resp = make_response(send_from_directory('/archives', path))
	if request.path.endswith('.css'): resp.headers.add("Content-Type", "text/css")
	return resp

@app.get('/e/<emoji>')
@limiter.exempt
def emoji(emoji):
	if not emoji.endswith('.webp'): abort(404)
	resp = make_response(send_from_directory('assets/images/emojis', emoji))
	resp.headers.remove("Cache-Control")
	resp.headers.add("Cache-Control", "public, max-age=3153600")
	resp.headers.remove("Content-Type")
	resp.headers.add("Content-Type", "image/webp")
	return resp

@app.get('/i/<path:path>')
@limiter.exempt
def image(path):
	resp = make_response(send_from_directory('assets/images', path))
	if request.path.endswith('.webp') or request.path.endswith('.gif') or request.path.endswith('.ttf') or request.path.endswith('.woff2'):
		resp.headers.remove("Cache-Control")
		resp.headers.add("Cache-Control", "public, max-age=3153600")

	if request.path.endswith('.webp'):
		resp.headers.remove("Content-Type")
		resp.headers.add("Content-Type", "image/webp")

	return resp

@app.get('/assets/<path:path>')
@app.get('/static/assets/<path:path>')
@limiter.exempt
def static_service(path):
	resp = make_response(send_from_directory('assets', path))
	if request.path.endswith('.webp') or request.path.endswith('.gif') or request.path.endswith('.ttf') or request.path.endswith('.woff2'):
		resp.headers.remove("Cache-Control")
		resp.headers.add("Cache-Control", "public, max-age=3153600")

	if request.path.endswith('.webp'):
		resp.headers.remove("Content-Type")
		resp.headers.add("Content-Type", "image/webp")

	return resp

@app.get('/images/<path>')
@app.get('/hostedimages/<path>')
@app.get("/static/images/<path>")
@limiter.exempt
def images(path):
	resp = make_response(send_from_directory('/images', path))
	resp.headers.remove("Cache-Control")
	resp.headers.add("Cache-Control", "public, max-age=3153600")
	resp.headers.remove("Content-Type")
	resp.headers.add("Content-Type" ,"image/webp")
	return resp

@app.get('/videos/<path>')
@limiter.exempt
def videos(path):
	resp = make_response(send_from_directory('/videos', path))
	resp.headers.remove("Cache-Control")
	resp.headers.add("Cache-Control", "public, max-age=3153600")
	return resp

@app.get('/audio/<path>')
@limiter.exempt
def audio(path):
	resp = make_response(send_from_directory('/audio', path))
	resp.headers.remove("Cache-Control")
	resp.headers.add("Cache-Control", "public, max-age=3153600")
	return resp

@app.get("/robots.txt")
def robots_txt():
	try: f = send_file("assets/robots.txt")
	except:
		print('/robots.txt', flush=True)
		abort(404)
	return f

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
@auth_required
def badges(v):
	badges, counts = badge_list(SITE)
	return render_template("badges.html", v=v, badges=badges, counts=counts)

@app.get("/blocks")
@auth_required
def blocks(v):


	blocks=g.db.query(UserBlock).all()
	users = []
	targets = []
	for x in blocks:
		acc_user = get_account(x.user_id)
		acc_tgt  = get_account(x.target_id)
		if acc_user.shadowbanned or acc_tgt.shadowbanned: continue
		users.append(acc_user)
		targets.append(acc_tgt)

	return render_template("blocks.html", v=v, users=users, targets=targets)

@app.get("/banned")
@auth_required
def banned(v):

	users = g.db.query(User).filter(User.is_banned > 0, User.unban_utc == 0).all()
	return render_template("banned.html", v=v, users=users)

@app.get("/formatting")
@auth_required
def formatting(v):

	return render_template("formatting.html", v=v)

@app.get("/service-worker.js")
def serviceworker():
	with open("files/assets/js/service-worker.js", "r", encoding="utf-8") as f:
		return Response(f.read(), mimetype='application/javascript')

@app.get("/settings/security")
@auth_required
def settings_security(v):

	return render_template("settings_security.html",
						   v=v,
						   mfa_secret=pyotp.random_base32() if not v.mfa_secret else None
						   )


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

	if request.headers.get("Authorization"): return {"data": [x.json for x in comments.all()]}

	try: page = max(int(request.values.get("page", 1)), 1)
	except: page = 1

	comments = comments.offset(25 * (page - 1)).limit(26).all()
	next_exists = len(comments) > 25
	comments = comments[:25]
	return render_template("transfers.html", v=v, page=page, comments=comments, standalone=True, next_exists=next_exists)