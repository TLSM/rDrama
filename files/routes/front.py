from files.helpers.wrappers import *
from files.helpers.get import *
from files.helpers.discord import *
from files.helpers.const import *
from files.helpers.sorting_and_time import *
from files.__main__ import app, cache, limiter
from files.classes.submission import Submission
from files.helpers.awards import award_timers

@app.get("/")
@app.get("/catalog")
@app.get("/h/<sub>")
@app.get("/s/<sub>")
@app.get("/logged_out")
@app.get("/logged_out/catalog")
@app.get("/logged_out/h/<sub>")
@app.get("/logged_out/s/<sub>")
@limiter.limit("3/second;30/minute;5000/hour;10000/day")
@auth_desired
def front_all(v, sub=None, subdomain=None):

	if not v and not request.path.startswith('/logged_out'):
		r = request.full_path
		if r == '/?': r = '/'
		return redirect(f"/logged_out{r}")
	if v and request.path.startswith('/logged_out'): return redirect(request.full_path.replace('/logged_out',''))

	if sub: sub = g.db.query(Sub).filter_by(name=sub.strip().lower()).one_or_none()
	
	if (request.path.startswith('/h/') or request.path.startswith('/s/')) and not sub: abort(404)

	try: page = max(int(request.values.get("page", 1)), 1)
	except: abort(400)

	if v:
		defaultsorting = v.defaultsorting
		if sub or SITE_NAME != 'rDrama': defaulttime = 'all'
		else: defaulttime = v.defaulttime
	else:
		defaultsorting = "hot"
		if sub or SITE_NAME != 'rDrama': defaulttime = 'all'
		else: defaulttime = DEFAULT_TIME_FILTER

	sort=request.values.get("sort", defaultsorting)
	t=request.values.get('t', defaulttime)
	ccmode=request.values.get('ccmode', "false").lower()
	
	try: gt=int(request.values.get("after", 0))
	except: gt=0

	try: lt=int(request.values.get("before", 0))
	except: lt=0

	if sort == 'hot': default = True
	else: default = False

	pins = session.get(sort, default)

	ids, next_exists = frontlist(sort=sort,
					page=page,
					t=t,
					v=v,
					ccmode=ccmode,
					filter_words=v.filter_words if v else [],
					gt=gt,
					lt=lt,
					sub=sub,
					site=SITE,
					pins=pins
					)

	posts = get_posts(ids, v=v)
	
	if v:
		if v.hidevotedon: posts = [x for x in posts if not hasattr(x, 'voted') or not x.voted]
		award_timers(v)

	if request.headers.get("Authorization"): return {"data": [x.json for x in posts], "next_exists": next_exists}
	return render_template("home.html", v=v, listing=posts, next_exists=next_exists, sort=sort, t=t, page=page, ccmode=ccmode, sub=sub, home=True, pins=pins)



@cache.memoize(timeout=86400)
def frontlist(v=None, sort="hot", page=1, t="all", ids_only=True, ccmode="false", filter_words='', gt=0, lt=0, sub=None, site=None, pins=True):

	posts = g.db.query(Submission)
	
	if v and v.hidevotedon:
		voted = [x[0] for x in g.db.query(Vote.submission_id).filter_by(user_id=v.id).all()]
		posts = posts.filter(Submission.id.notin_(voted))

	if sub: posts = posts.filter_by(sub=sub.name)
	elif v: posts = posts.filter(or_(Submission.sub == None, Submission.sub.notin_(v.all_blocks)))

	if gt: posts = posts.filter(Submission.created_utc > gt)
	if lt: posts = posts.filter(Submission.created_utc < lt)

	if not gt and not lt:
		posts = apply_time_filter(t, posts, Submission)

	if (ccmode == "true"):
		posts = posts.filter(Submission.club == True)

	posts = posts.filter_by(is_banned=False, private=False, deleted_utc = 0)

	if pins and ccmode == "false" and not gt and not lt:
		if sub: posts = posts.filter_by(hole_pinned=None)
		else: posts = posts.filter_by(stickied=None)

	if v:
		posts = posts.filter(Submission.author_id.notin_(v.userblocks))

	if v and filter_words:
		for word in filter_words:
			word  = word.replace('\\', '').replace('_', '\_').replace('%', '\%').strip()
			posts=posts.filter(not_(Submission.title.ilike(f'%{word}%')))

	if not (v and v.shadowbanned):
		posts = posts.join(Submission.author).filter(User.shadowbanned == None)

	if SITE == 'rdrama.net': num = 5
	else: num = 0.5

	if sort == 'hot':
		ti = int(time.time()) + 3600
		if SITE == 'watchpeopledie.co':
			posts = posts.order_by(-1000000*(Submission.upvotes - Submission.downvotes + 1 + Submission.comment_count/num)/(func.power(((ti - Submission.created_utc)/1000), 1.23)), Submission.created_utc.desc())
		else:
			posts = posts.order_by(-1000000*(Submission.realupvotes + 1 + Submission.comment_count/num)/(func.power(((ti - Submission.created_utc)/1000), 1.23)), Submission.created_utc.desc())
	elif sort == "bump":
		posts = posts.filter(Submission.comment_count > 1).order_by(Submission.bump_utc.desc(), Submission.created_utc.desc())
	else:
		posts = sort_posts(sort, posts)

	if v: size = v.frontsize or 0
	else: size = 25

	posts = posts.offset(size * (page - 1)).limit(size+1).all()

	next_exists = (len(posts) > size)

	posts = posts[:size]

	if pins and page == 1 and ccmode == "false" and not gt and not lt:
		if sub:
			pins = g.db.query(Submission).filter(Submission.sub == sub.name, Submission.hole_pinned != None)
		else:
			pins = g.db.query(Submission).filter(Submission.stickied != None, Submission.is_banned == False)
			
			if v:
				pins = pins.filter(or_(Submission.sub == None, Submission.sub.notin_(v.all_blocks)))
				for pin in pins:
					if pin.stickied_utc and int(time.time()) > pin.stickied_utc:
						pin.stickied = None
						pin.stickied_utc = None
						g.db.add(pin)


		if v: pins = pins.filter(Submission.author_id.notin_(v.userblocks))

		pins = pins.order_by(Submission.created_utc.desc()).all()

		posts = pins + posts

	if ids_only: posts = [x.id for x in posts]


	return posts, next_exists


@app.get("/random_post")
@auth_required
def random_post(v):

	p = g.db.query(Submission.id).filter(Submission.deleted_utc == 0, Submission.is_banned == False, Submission.private == False).order_by(func.random()).first()

	if p: p = p[0]
	else: abort(404)

	return redirect(f"/post/{p}")


@app.get("/random_user")
@auth_required
def random_user(v):

	u = g.db.query(User.username).filter(User.song != None).order_by(func.random()).first()
	
	if u: u = u[0]
	else: return "No users have set a profile anthem so far!"

	return redirect(f"/@{u}")


@app.get("/comments")
@auth_required
def all_comments(v):


	try: page = max(int(request.values.get("page", 1)), 1)
	except: page = 1

	sort=request.values.get("sort", "new")
	t=request.values.get("t", DEFAULT_TIME_FILTER)

	try: gt=int(request.values.get("after", 0))
	except: gt=0

	try: lt=int(request.values.get("before", 0))
	except: lt=0

	idlist = comment_idlist(v=v,
							page=page,
							sort=sort,
							t=t,
							gt=gt,
							lt=lt,
							site=SITE
							)

	comments = get_comments(idlist, v=v)

	next_exists = len(idlist) > 25

	idlist = idlist[:25]

	if request.headers.get("Authorization"): return {"data": [x.json for x in comments]}
	return render_template("home_comments.html", v=v, sort=sort, t=t, page=page, comments=comments, standalone=True, next_exists=next_exists)



@cache.memoize(timeout=86400)
def comment_idlist(page=1, v=None, nsfw=False, sort="new", t="all", gt=0, lt=0, site=None):

	comments = g.db.query(Comment.id).filter(Comment.parent_submission != None, Comment.author_id.notin_(v.userblocks))

	if v.admin_level < 2:
		private = [x[0] for x in g.db.query(Submission.id).filter(Submission.private == True).all()]

		comments = comments.filter(Comment.is_banned==False, Comment.deleted_utc == 0, Comment.parent_submission.notin_(private))


	if not v.paid_dues:
		club = [x[0] for x in g.db.query(Submission.id).filter(Submission.club == True).all()]
		comments = comments.filter(Comment.parent_submission.notin_(club))


	if gt: comments = comments.filter(Comment.created_utc > gt)
	if lt: comments = comments.filter(Comment.created_utc < lt)

	if not gt and not lt:
		comments = apply_time_filter(t, comments, Comment)

	comments = sort_comments(sort, comments)

	comments = comments.offset(25 * (page - 1)).limit(26).all()
	return [x[0] for x in comments]