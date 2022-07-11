from flask import g
import time
from files.helpers.alerts import send_repeatable_notification
from files.helpers.const import bots
from files.helpers.discord import remove_role
from files.classes.badges import Badge
from files.classes.user import User

def award_timers(v, bot=False):
	now = time.time()
	dirty = False

	def notify_if_not_bot(msg):
		if not bot:
			send_repeatable_notification(v.id,msg)

	if v.patron_utc and v.patron_utc < now:
		v.patron = 0
		v.patron_utc = 0
		notify_if_not_bot("Your paypig status has expired!")
		if not bot and v.discord_id: remove_role(v, "1")
		dirty = True
	if v.unban_utc and v.unban_utc < now:
		v.is_banned = 0
		v.unban_utc = 0
		v.ban_evade = 0
		v.ban_reason = None
		notify_if_not_bot("You have been unbanned!")
		dirty = True
	if v.agendaposter and v.agendaposter < now:
		v.agendaposter = 0
		notify_if_not_bot("Your chud theme has expired!")
		badge = v.has_badge(28)
		if badge: g.db.delete(badge)
		dirty = True
	if v.flairchanged and v.flairchanged < now:
		v.flairchanged = None
		notify_if_not_bot("Your flair lock has expired. You can now change your flair!")
		badge = v.has_badge(96)
		if badge: g.db.delete(badge)
		dirty = True
	if v.marseyawarded and v.marseyawarded < now:
		v.marseyawarded = None
		notify_if_not_bot("Your marsey award has expired!")
		badge = v.has_badge(98)
		if badge: g.db.delete(badge)
		dirty = True
	if v.longpost and v.longpost < now:
		v.longpost = None
		notify_if_not_bot("Your pizzashill award has expired!")
		badge = v.has_badge(97)
		if badge: g.db.delete(badge)
		dirty = True
	if v.bird and v.bird < now:
		v.bird = None
		notify_if_not_bot("Your bird site award has expired!")
		badge = v.has_badge(95)
		if badge: g.db.delete(badge)
		dirty = True
	if v.progressivestack and v.progressivestack < now:
		v.progressivestack = None
		notify_if_not_bot("Your progressive stack has expired!")
		badge = v.has_badge(94)
		if badge: g.db.delete(badge)
		dirty = True
	if v.rehab and v.rehab < now:
		v.rehab = None
		notify_if_not_bot("Your rehab has finished!")
		badge = v.has_badge(109)
		if badge: g.db.delete(badge)
		dirty = True
	if v.deflector and v.deflector < now:
		v.deflector = None
		notify_if_not_bot("Your deflector has expired!")
		dirty = True

	if dirty:
		g.db.add(v)

def award_timers_bots_task():
	accs = g.db.query(User).filter(User.id.in_(bots))
	for u in accs:
		award_timers(u, bot=True)
