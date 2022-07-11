from files.helpers.wrappers import *
from files.helpers.get import *
from files.helpers.const import *
from files.__main__ import app
import time

@app.post("/clear")
@auth_required
def clear(v):
	notifs = g.db.query(Notification).join(Notification.comment).filter(Notification.read == False, Notification.user_id == v.id).all()
	for n in notifs:
		n.read = True
		g.db.add(n)
	v.last_viewed_post_notifs = int(time.time())
	g.db.add(v)
	return {"message": "Notifications cleared!"}


@app.get("/unread")
@auth_required
def unread(v):
	listing = g.db.query(Notification, Comment).join(Notification.comment).filter(
		Notification.read == False,
		Notification.user_id == v.id,
		Comment.is_banned == False,
		Comment.deleted_utc == 0,
	).order_by(Notification.created_utc.desc()).all()

	for n, c in listing:
		n.read = True
		g.db.add(n)

	return {"data":[x[1].json_core for x in listing]}



@app.get("/notifications/modmail")
@admin_level_required(2)
def notifications_modmail(v):
	try: page = max(int(request.values.get("page", 1)), 1)
	except: page = 1

	comments = g.db.query(Comment).filter(Comment.sentto==2).order_by(Comment.id.desc()).offset(25*(page-1)).limit(26).all()
	next_exists = (len(comments) > 25)
	listing = comments[:25]

	g.db.commit()

	if request.headers.get("Authorization"): return {"data":[x.json for x in listing]}

	return render_template("notifications.html",
							v=v,
							notifications=listing,
							next_exists=next_exists,
							page=page,
							standalone=True,
							render_replies=True,
						   )



@app.get("/notifications/messages")
@auth_required
def notifications_messages(v):
	try: page = max(int(request.values.get("page", 1)), 1)
	except: page = 1

	if v and (v.shadowbanned or v.admin_level > 2):
		comments = g.db.query(Comment).filter(Comment.sentto != None, or_(Comment.author_id==v.id, Comment.sentto==v.id), Comment.parent_submission == None, Comment.level == 1).order_by(Comment.id.desc()).offset(25*(page-1)).limit(26).all()
	else:
		comments = g.db.query(Comment).join(Comment.author).filter(User.shadowbanned == None, Comment.sentto != None, or_(Comment.author_id==v.id, Comment.sentto==v.id), Comment.parent_submission == None, Comment.level == 1).order_by(Comment.id.desc()).offset(25*(page-1)).limit(26).all()

	next_exists = (len(comments) > 25)
	listing = comments[:25]

	g.db.commit()

	if request.headers.get("Authorization"): return {"data":[x.json for x in listing]}

	return render_template("notifications.html",
							v=v,
							notifications=listing,
							next_exists=next_exists,
							page=page,
							standalone=True,
							render_replies=True,
						   )


@app.get("/notifications/posts")
@auth_required
def notifications_posts(v):
	try: page = max(int(request.values.get("page", 1)), 1)
	except: page = 1

	listing = [x[0] for x in g.db.query(Submission.id).filter(
		or_(
			Submission.author_id.in_(v.followed_users),
			Submission.sub.in_(v.followed_subs)
		),
		Submission.deleted_utc == 0,
		Submission.is_banned == False,
		Submission.private == False,
		Submission.author_id != v.id,
	).order_by(Submission.created_utc.desc()).offset(25 * (page - 1)).limit(26).all()]

	next_exists = (len(listing) > 25)
	listing = listing[:25]
	listing = get_posts(listing, v=v)

	for p in listing:
		p.unread = p.created_utc > v.last_viewed_post_notifs

	v.last_viewed_post_notifs = int(time.time())
	g.db.add(v)

	if request.headers.get("Authorization"): return {"data":[x.json for x in listing]}

	return render_template("notifications.html",
							v=v,
							notifications=listing,
							next_exists=next_exists,
							page=page,
							standalone=True,
							render_replies=True,
						   )


@app.get("/notifications/modactions")
@admin_level_required(NOTIF_MODACTION_JL_MIN)
def notifications_modactions(v):
	try: page = max(int(request.values.get("page", 1)), 1)
	except: page = 1

	notifications = g.db.query(Notification, Comment) \
		.join(Notification.comment) \
		.filter(Notification.user_id == v.id, 
			Comment.body_html.like(f'%<p>{NOTIF_MODACTION_PREFIX}%'),
			Comment.parent_submission == None, Comment.author_id == AUTOJANNY_ID) \
		.order_by(Notification.created_utc.desc()).offset(25 * (page - 1)).limit(101).all()
	listing = []

	for index, x in enumerate(notifications[:100]):
		n, c = x
		if n.read and index > 24: break
		elif not n.read:
			n.read = True
			c.unread = True
			g.db.add(n)
		if n.created_utc > 1620391248: c.notif_utc = n.created_utc
		listing.append(c)

	next_exists = (len(notifications) > len(listing))

	g.db.commit()

	if request.headers.get("Authorization"): return {"data":[x.json for x in listing]}

	return render_template("notifications.html",
							v=v,
							notifications=listing,
							next_exists=next_exists,
							page=page,
							standalone=True,
							render_replies=True,
						   )



@app.get("/notifications/reddit")
@auth_required
def notifications_reddit(v):
	try: page = max(int(request.values.get("page", 1)), 1)
	except: page = 1

	if not v.can_view_offsitementions: abort(403)

	notifications = g.db.query(Notification, Comment).join(Notification.comment).filter(
		Notification.user_id == v.id,
		Comment.body_html.like('%<p>New site mention%<a href="https://old.reddit.com/r/%'),
		Comment.parent_submission == None,
		Comment.author_id == AUTOJANNY_ID
	).order_by(Notification.created_utc.desc()).offset(25 * (page - 1)).limit(101).all()

	listing = []

	for index, x in enumerate(notifications[:100]):
		n, c = x
		if n.read and index > 24: break
		elif not n.read:
			n.read = True
			c.unread = True
			g.db.add(n)
		if n.created_utc > 1620391248: c.notif_utc = n.created_utc
		listing.append(c)

	next_exists = (len(notifications) > len(listing))

	g.db.commit()

	if request.headers.get("Authorization"): return {"data":[x.json for x in listing]}

	return render_template("notifications.html",
							v=v,
							notifications=listing,
							next_exists=next_exists,
							page=page,
							standalone=True,
							render_replies=True,
						   )




@app.get("/notifications")
@auth_required
def notifications(v):
	try: page = max(int(request.values.get("page", 1)), 1)
	except: page = 1

	comments = g.db.query(Comment, Notification).join(Notification.comment).filter(
		Notification.user_id == v.id,
		Comment.is_banned == False,
		Comment.deleted_utc == 0,
		Comment.body_html.notlike('%<p>New site mention%<a href="https://old.reddit.com/r/%'),
		Comment.body_html.notlike(f'%<p>{NOTIF_MODACTION_PREFIX}%')
	).order_by(Notification.created_utc.desc())

	if not (v and (v.shadowbanned or v.admin_level > 2)):
		comments = comments.join(Comment.author).filter(User.shadowbanned == None)

	comments = comments.offset(25 * (page - 1)).limit(26).all()

	next_exists = (len(comments) > 25)
	comments = comments[:25]

	cids = [x[0].id for x in comments]

	comms = get_comments(cids, v=v)

	listing = []
	for c, n in comments:
		if n.created_utc > 1620391248: c.notif_utc = n.created_utc
		if not n.read:
			n.read = True
			c.unread = True
			g.db.add(n)

		if c.parent_submission:
			if c.replies2 == None:
				c.replies2 = g.db.query(Comment).filter_by(parent_comment_id=c.id).filter(or_(Comment.author_id == v.id, Comment.id.in_(cids))).all()
				for x in c.replies2:
					if x.replies2 == None: x.replies2 = []
			count = 0
			while count < 50 and c.parent_comment and (c.parent_comment.author_id == v.id or c.parent_comment.id in cids):
				count += 1
				c = c.parent_comment
				if c.replies2 == None:
					c.replies2 = g.db.query(Comment).filter_by(parent_comment_id=c.id).filter(or_(Comment.author_id == v.id, Comment.id.in_(cids))).all()
					for x in c.replies2:
						if x.replies2 == None:
							x.replies2 = g.db.query(Comment).filter_by(parent_comment_id=x.id).filter(or_(Comment.author_id == v.id, Comment.id.in_(cids))).all()
		else:
			while c.parent_comment:
				c = c.parent_comment
			c.replies2 = g.db.query(Comment).filter_by(parent_comment_id=c.id).order_by(Comment.id).all()

		if c not in listing: listing.append(c)

	g.db.commit()

	if request.headers.get("Authorization"): return {"data":[x.json for x in listing]}

	return render_template("notifications.html",
							v=v,
							notifications=listing,
							next_exists=next_exists,
							page=page,
							standalone=True,
							render_replies=True,
						   )