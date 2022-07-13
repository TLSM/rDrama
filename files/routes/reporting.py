from files.helpers.wrappers import *
from files.helpers.get import *
from files.helpers.alerts import *
from flask import g
from files.__main__ import app, limiter
from os import path
from files.helpers.sanitize import filter_emojis_only

@app.post("/report/post/<pid>")
@limiter.limit("1/second;30/minute;200/hour;1000/day")
@limiter.limit("1/second;30/minute;200/hour;1000/day", key_func=lambda:f'{SITE}-{session.get("lo_user")}')
@auth_required
def api_flag_post(pid, v):

	post = get_post(pid)

	reason = request.values.get("reason", "").strip()

	if blackjack and any(i in reason.lower() for i in blackjack.split()):
		v.shadowbanned = 'AutoJanny'
		send_repeatable_notification(CARP_ID, f"reports on {post.permalink}")
		send_repeatable_notification(AEVANN_ID, f"reports on {post.permalink}")

	reason = reason[:100]

	if not reason.startswith('!'):
		existing = g.db.query(Flag.post_id).filter_by(user_id=v.id, post_id=post.id).one_or_none()
		if existing: return "", 409

	reason = filter_emojis_only(reason)

	if len(reason) > 350: return {"error": "Too long."}

	if reason.startswith('!') and v.admin_level > 1:
		post.flair = reason[1:]
		g.db.add(post)
		ma=ModAction(
			kind="flair_post",
			user_id=v.id,
			target_submission_id=post.id,
			_note=f'"{post.flair}"'
		)
		g.db.add(ma)
	elif reason.startswith('/h/') and v.admin_level >= 2 or v.id == post.author_id:

		sub_from = post.sub
		sub_to = reason[3:].strip().lower()
		sub_to = g.db.query(Sub).filter_by(name=sub_to).one_or_none()
		sub_to = sub_to.name if sub_to else None

		if sub_from == sub_to: abort(400)
		post.sub = sub_to
		g.db.add(post)

		if v.admin_level and v.id != post.author_id:
			sub_from_str = 'main feed' if sub_from is None else \
				f'<a href="/h/{sub_from}">/h/{sub_from}</a>'
			sub_to_str = 'main feed' if sub_to is None else \
				f'<a href="/h/{sub_to}">/h/{sub_to}</a>'
			ma = ModAction(
				kind='move_hole',
				user_id=v.id,
				target_submission_id=post.id,
				_note=f'{sub_from_str} → {sub_to_str}',
			)
			g.db.add(ma)

		return {"message": f"Post moved to /h/{post.sub}"}
	else:
		flag = Flag(post_id=post.id, user_id=v.id, reason=reason)
		g.db.add(flag)


	return {"message": "Post reported!"}


@app.post("/report/comment/<cid>")
@limiter.limit("1/second;30/minute;200/hour;1000/day")
@limiter.limit("1/second;30/minute;200/hour;1000/day", key_func=lambda:f'{SITE}-{session.get("lo_user")}')
@auth_required
def api_flag_comment(cid, v):

	comment = get_comment(cid)
	
	existing = g.db.query(CommentFlag.comment_id).filter_by( user_id=v.id, comment_id=comment.id).one_or_none()
	if existing: return "", 409

	reason = request.values.get("reason", "").strip()

	if blackjack and any(i in reason.lower() for i in blackjack.split()):
		v.shadowbanned = 'AutoJanny'
		send_repeatable_notification(CARP_ID, f"reports on {comment.permalink}")
		send_repeatable_notification(AEVANN_ID, f"reports on {comment.permalink}")

	reason = reason[:100]

	reason = filter_emojis_only(reason)

	if len(reason) > 350: return {"error": "Too long."}

	flag = CommentFlag(comment_id=comment.id, user_id=v.id, reason=reason)

	g.db.add(flag)

	return {"message": "Comment reported!"}


@app.post('/del_report/post/<pid>/<uid>')
@limiter.limit("4/second;100/minute;300/hour;2000/day")
@admin_level_required(PERMS['FLAGS_REMOVE'])
def remove_report_post(v, pid, uid):

	try:
		pid = int(pid)
		uid = int(uid)
	except: abort(400)

	report = g.db.query(Flag).filter_by(post_id=pid, user_id=uid).one_or_none()

	if report:
		g.db.delete(report)

		ma=ModAction(
			kind="delete_report",
			user_id=v.id,
			target_submission_id=pid
		)

		g.db.add(ma)


	return {"message": "Report removed successfully!"}


@app.post('/del_report/comment/<cid>/<uid>')
@limiter.limit("4/second;100/minute;300/hour;2000/day")
@admin_level_required(PERMS['FLAGS_REMOVE'])
def remove_report_comment(v, cid, uid):
	
	cid = int(cid)
	uid = int(uid)
	
	report = g.db.query(CommentFlag).filter_by(comment_id=cid, user_id=uid).one_or_none()
	
	if report:
		g.db.delete(report)

		ma=ModAction(
			kind="delete_report",
			user_id=v.id,
			target_comment_id=cid
		)

		g.db.add(ma)


	return {"message": "Report removed successfully!"}