import time
from files.helpers.const import *
from sqlalchemy.sql import func

def apply_time_filter(t, objects, cls):
	now = int(time.time())
	if t == 'hour':
		cutoff = now - 3600
	elif t == 'day':
		cutoff = now - 86400
	elif t == 'week':
		cutoff = now - 604800
	elif t == 'month':
		cutoff = now - 2592000
	elif t == 'year':
		cutoff = now - 31536000
	else:
		cutoff = 0

	return objects.filter(cls.created_utc >= cutoff)

def sort_objects(sort, objects, cls, include_shadowbanned=False):
	if not include_shadowbanned:
		cls_user = cls.__mapper__.relationships['author'].entity.entity
		objects = objects.join(cls.author).filter(cls_user.shadowbanned == None)

	if sort == 'hot':
		ti = int(time.time()) + 3600
		if SITE_NAME == 'rDrama': metric = cls.realupvotes
		else: metric = cls.upvotes - cls.downvotes
		if cls.__name__ == "Submission": metric += cls.comment_count/5
		return objects.order_by(-1000000*(metric + 1)/(func.power(((ti - cls.created_utc)/1000), 1.23)), cls.created_utc.desc())
	elif sort == "bump" and cls.__name__ == "Submission":
		return objects.filter(cls.comment_count > 1).order_by(cls.bump_utc.desc(), cls.created_utc.desc())
	elif sort == "comments" and cls.__name__ == "Submission":
		return objects.order_by(cls.comment_count.desc(), cls.created_utc.desc())
	elif sort == "new":
		return objects.order_by(cls.created_utc.desc())
	elif sort == "old":
		return objects.order_by(cls.created_utc)
	elif sort == "controversial":
		return objects.order_by((cls.upvotes+1)/(cls.downvotes+1) + (cls.downvotes+1)/(cls.upvotes+1), cls.downvotes.desc(), cls.created_utc.desc())
	elif sort == "bottom":
		return objects.order_by(cls.upvotes - cls.downvotes, cls.created_utc.desc())
	elif sort == "top":
		return objects.order_by(cls.downvotes - cls.upvotes, cls.created_utc.desc())
