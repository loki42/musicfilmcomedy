# Music Film Comedy 
#
# Hopefully a useful base for web apps. 
#
# Copyright (c) 2012  Gravity Four
#
# by Loki Davison, Mirsad Makalic
#
#
# This is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# failover_connection is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
import cherrypy, json, datetime, os, itertools, re, urllib
from contextlib import contextmanager
from mako.lookup import TemplateLookup
import psycopg2
import psycopg2.extensions
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import NamedTupleCursor, RealDictCursor
from beaker.cache import CacheManager
from dateutil.rrule import rrule, DAILY
import GeoIP
from beaker.middleware import CacheMiddleware, SessionMiddleware
import beaker_extensions
from itsdangerous import Signer
from retools.cache import CacheRegion, cache_region, invalidate_function
import redis

import i18n_tool
from i18n_tool import ugettext as _
import babel

# all db queries return unicode
psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)

geoip = GeoIP.open('/usr/share/GeoIP/GeoLiteCity.dat', GeoIP.GEOIP_MEMORY_CACHE)
pool = ThreadedConnectionPool(1, 10, database='musicfilmcomedy')
SECRET_SIGN_KEY = 'randomkeygoeshere'



CacheRegion.add_region('short_term', expires=3600)
CacheRegion.invalidate('short_term')
manager = CacheManager(cache_regions={
    'short_term':{
        'type': 'memory',
        'expire': 60
        },
    'long_term':{
        'type': 'memory',
        'expire': 300
        }
    })

mylookup = TemplateLookup(
            input_encoding = 'utf-8',
            output_encoding='utf-8',
            directories=['templates'], 
            module_directory='/tmp/mako_modules', 
            cache_impl = 'beaker')
            # cache_args = {
            #         'manager':manager
            #     })

dthandler = lambda obj: obj.isoformat() if isinstance(obj, datetime.datetime) else None

def jsonify_date(*args, **kwargs):
    value = cherrypy.serving.request._json_inner_handler(*args, **kwargs)
    return json.dumps(value, default=dthandler)

@contextmanager
def get_db(tuple_cur=False, yield_conn=False, dict_cur=True):
    conn = pool.getconn()
    try:
        if dict_cur:
            yield conn.cursor(cursor_factory=RealDictCursor)
        elif tuple_cur and not yield_conn:
            yield conn.cursor(cursor_factory=NamedTupleCursor)
        elif tuple_cur:
            yield (conn, conn.cursor(cursor_factory=NamedTupleCursor))
        else:
            yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        pool.putconn(conn)


def uid_is_valid(user, uid, festival):
    s = Signer(SECRET_SIGN_KEY)
    # cookie is uid hashed with our private key, check that the cookie was sent
    cookie = cherrypy.request.cookie.get('mfc_sch'+str(uid))
    if cookie:
        # and if it's correct
        return str(uid) == s.unsign(str(cookie.value))
    elif user:
        #check if this user is the user that's allowed for this uid.
        with get_db() as cur:
            cur.execute("select id from mfc.schedules where username = %s and festival = %s", [user['email'], festival])
            r = cur.fetchall()
        if r:
            return str(uid) == str(r[0]['id'])
    # else not valid
    else:
        return False

def to_tuple(a):
    if isinstance(a, str):
        try:
            a = json.loads(a)
            if isinstance(a, list):
                return tuple(a)
            else:
                return (a,)
        except ValueError:#a is just a string, not a json structure.
            return (a,)
    if isinstance(a, list):
        return tuple(a)
    else:
        return (a,)

def query_to_json(query, args):
    with get_db() as cur:
        cur.execute(query, args)
        return cur.fetchall()

def pretty_param(param):
    """
    for pretty urls, currently just replace _ with ' '
    """
    return param.replace('_', ' ')

def get_lang(lang):
    default = 'en'
    mo_dir = os.path.join(os.path.abspath(os.curdir), 'locale')
    domain = 'musicfilmcomedy'

    langs = [lang.replace('-', '_')]
    langs.append(default)
    loc = i18n_tool.load_translation(langs, mo_dir, domain)
    cherrypy.response.i18n = loc
    cherrypy.response.current_lang = lang
    i18n_tool.set_lang()

def get_all_langs():
    with get_db() as cur:
        cur.execute("select distinct(lang) from mfc.descriptions")
        all_available_languages = [a['lang'] for a in cur.fetchall()]
        return all_available_languages

def get_max_eyes():
    with get_db() as cur:
        cur.execute("select max(followers+likes) as max from mfc.acts")
        return cur.fetchall()[0]['max']

def add_translated_descriptions(table, objects):
    processed = []
    with get_db() as cur:
        for obj in objects:
            cur.execute("""
            select val from mfc.descriptions
            where lang = %s 
            and col = 'description' and feature=%s
            and key=%s""", [cherrypy.response.current_lang, table, obj['name']])
            r = cur.fetchall()
            if r:
                obj['description'] = r[0]['val']
            cur.execute("""
            select val from mfc.descriptions
            where lang = %s 
            and col = 'name' and feature=%s
            and key=%s""", [cherrypy.response.current_lang, table, obj['name']])
            r = cur.fetchall()
            if r:
                obj['name_in_locale'] = r[0]['val']
            processed.append(obj)
    return processed

MAX_EYES = get_max_eyes()

class JsonBackend(object):
    def create_user(self, email, full_name, fb_user_id, fb_access_token):
        with get_db() as cur:
            update = """
                UPDATE mfc.users SET timestamp=now(), full_name=%s, facebook_user_id=%s, facebook_access_token=%s WHERE username=%s;
                """

            insert = """
                INSERT INTO mfc.users (timestamp, username, full_name, facebook_user_id, facebook_access_token)
                        SELECT now(), %s, %s, %s, %s
                        WHERE NOT EXISTS(SELECT 1 FROM mfc.users WHERE username=%s)
                    """

            cur.execute(update + insert,
                        [full_name, fb_user_id, fb_access_token, email,
                        email, full_name, fb_user_id, fb_access_token, email])

    @cherrypy.expose
    def friends_attending_festival(self, friends, festival):
        with get_db() as cur:
            friends = tuple(json.loads(friends))
            
            cur.execute("""
                        SELECT * FROM mfc.users 
                            INNER JOIN mfc.festival_attendence ON users.username=festival_attendence.username
                            WHERE facebook_user_id in %s AND festival=%s
                        """, [friends, festival])
            return [x['facebook_user_id'] for x in cur.fetchall()]

    @cherrypy.expose
    def friends_acts_at_festival(self, friends, festival, day):
        friends = tuple(json.loads(friends))
        with get_db() as cur:
            cur.execute("""
                        SELECT * FROM mfc.users 
                            INNER JOIN mfc.attending_act_at_venue ON users.username=attending_act_at_venue.username
                            WHERE facebook_user_id in %s AND festival=%s AND day=%s
                        """, [friends, festival, day])
            return cur.fetchall()    
    
    @cherrypy.expose
    def list_festivals(self, latitude=None, longitude=None, limit=20, offset=0):
        """
        list all for given location

        lat long pair must be int (only degrees i.e 134) for for cacheing to be useful.

        """
        #FIXME should remove GIS columns from returned result. 
        with get_db() as cur:
            if latitude and longitude:
                # the false param to the distance func tells it use sphere
                # instead of spheroid, for performance
                cur.execute("""
                SELECT *,
                ST_Distance(location, ST_GeographyFromText('SRID=4326;POINT(%s %s)'), false) as distance
                FROM mfc.festivals 
                where (start_date > now() - interval '2 days' or end_date > now() - interval '2 day') and start_date < now() + interval '3 months'
                order by ST_Distance(location, ST_GeographyFromText('SRID=4326;POINT(%s %s)'), false) - (COALESCE(bing_score, 0) / 1000 + COALESCE(likes,0) + COALESCE(followers,0))
                limit %s offset %s""", [float(longitude), float(latitude), float(longitude), float(latitude), limit, offset])
            else:
                cur.execute("select * from mfc.festivals limit %s offset %s", [limit, offset])
            r = cur.fetchall()
            if cherrypy.response.current_lang != 'en':
                r = add_translated_descriptions('festivals', r)
            return r

    @cherrypy.expose
    def festival_countries(self):
        with get_db() as cur:
            cur.execute("""
                SELECT DISTINCT country from mfc.festivals ORDER BY country;
            """)
            return [result['country'] for result in cur.fetchall()]

    @cherrypy.expose
    def search_festivals(self, query='melbourne festival', latitude=None, longitude=None, limit=20, offset=0):
        """
        query is user entered query string

        lat long pair must be int (only degrees i.e 134) for for cacheing to be useful.
        """
        #simple transform via plainto_tsquery 

        with get_db() as cur:
            if latitude:
                cur.execute("""
                    SELECT *
        FROM mfc.festivals, plainto_tsquery(%s) query
        WHERE name || ' ' || city  || ' ' || COALESCE(state, '')  || ' ' || country   || ' ' ||  style @@ query
        ORDER BY ST_Distance(location, ST_GeographyFromText('SRID=4326;POINT(%s %s)'), false) - (COALESCE(bing_score, 0) / 1000 + COALESCE(likes,0) +
        COALESCE(followers,0)) asc
        LIMIT %s offset %s;""", [query, longitude, latitude, limit, offset])
            else:
                cur.execute("""
                SELECT *
        FROM mfc.festivals, plainto_tsquery(%s) query
        WHERE name || ' ' || city  || ' ' || COALESCE(state, '')  || ' ' || country   || ' ' ||  style @@ query
        ORDER BY (COALESCE(bing_score, 0) / 1000 + COALESCE(likes,0) +
        COALESCE(followers,0)) desc
        LIMIT %s offset %s;""", [query, limit, offset])
            
            r = cur.fetchall()
            if cherrypy.response.current_lang != 'en':
                r = add_translated_descriptions('festivals', r)
            return r

    @cherrypy.expose
    def festivals_from_country(self, country):
        r = query_to_json("""
            select * from mfc.festivals where country = %s
            """, [country])
        if cherrypy.response.current_lang != 'en':
            r = add_translated_descriptions('festivals', r)
        return r


    @cherrypy.expose
    def festival(self, festival_names):
        festival_names = to_tuple(festival_names)
        ##print "\n\n\n\n #####", cherrypy.response.current_lang
        with get_db() as cur:
            cur.execute("""
            select * from mfc.festivals where name in %s
            """, [festival_names])
            f = cur.fetchall()
            if cherrypy.response.current_lang != 'en':
                f = add_translated_descriptions('festivals', f)
        return f

    @cherrypy.expose
    def festival_all_info(self, festival_name):
        with get_db() as cur:
            cur.execute("""
            select * from mfc.festivals where name = %s
            """, [festival_name])
            festival = cur.fetchall()
            cur.execute("""
            select * from mfc.venues where festival = %s
            """, [festival_name])
            venues = cur.fetchall()
            cur.execute("""
            select distinct on (a.name) a.* 
            from mfc.acts a, mfc.acts_at_venues av
            where a.name=av.act and av.festival=%s;
            """, [festival_name])
            acts = cur.fetchall()
            cur.execute("select * from mfc.acts_at_venues where festival=%s order by start_time", [festival_name])
            acts_at_venues = cur.fetchall()
            return {'festival':festival, 'venues':venues, 'act':acts, 'acts_at_venues':acts_at_venues}

    @cache_region('short_term')
    @cherrypy.expose
    def acts_by_venue_per_day(self, festival, day):
        with get_db() as cur:
            cur.execute("""
            select * from mfc.venues where festival = %s
            """, [festival])
            venues = [dict(a) for a in cur.fetchall()]
            
            for venue in venues:
                cur.execute("""
                select * 
                from mfc.acts_at_venues 
                where festival=%s and
                    venue=%s
                    and (start_time::timestamp >= %s::timestamp + INTERVAL '2 hour')
                    and (start_time::timestamp <= %s::timestamp + INTERVAL '1 day 2 hour')
                    order by start_time
                """, [festival, venue['name'], day, day])
                #print cur.query
                venue['acts_at_venues'] = [dict(a) for a in cur.fetchall()]

            return venues
    
    @cache_region('short_term')
    @cherrypy.expose
    def festival_acts_by_day(self, festival, day):
        with get_db() as cur:
            cur.execute("""
            select * from mfc.acts_at_venues
            where festival=%s
                and (start_time::timestamp >= %s::timestamp + INTERVAL '2 hour')
                and (start_time::timestamp <= %s::timestamp + INTERVAL '1 day 2 hour')
            order by start_time
            """, [festival, day, day])            
            return [dict(a) for a in cur.fetchall()]
    
    @cache_region('short_term')
    @cherrypy.expose
    def festival_first_act_time(self, festival, day):
        with get_db() as cur:
            cur.execute("""
            select start_time from mfc.acts_at_venues where festival=%s
            and start_time::date = %s::date
            order by start_time limit 1""", [festival, day])
            return cur.fetchall()[0]['start_time']

    @cherrypy.expose
    def festival_days(self, festival):
        """
        return what a list of the days this festival is on
        """
        r = query_to_json("""
            select start_date, end_date from mfc.festivals where name = %s
            """, [festival])[0]
        if not r['end_date']:
            return []
        return list(rrule(DAILY,
               dtstart=r['start_date'],
               until=r['end_date']))

    #
    # Lineups
    #
    @cherrypy.expose
    def get_lineup(self, festival='Melbourne International Comedy Festival'):
        """
        this lineup looks right/wrong button, not for official lineups. View other lineups by score? 
        """
        return query_to_json("select * from mfc.acts_at_venues where festival=%s order by start_time", [festival])

    @cherrypy.expose
    def submit_lineup(self, lineup_details):
        """
        same JSON format as returned buy get_lineup
        """
        pass

    #
    # Acts
    #
    @cherrypy.expose
    def act(self, names):
        names = to_tuple(names)
        names = tuple([str(name) for name in names])
        f = query_to_json("""
            select * from mfc.acts where name in %s
            """, [names])
        if cherrypy.response.current_lang != 'en':
            f = add_translated_descriptions('acts', f)
        return f

    @cherrypy.expose
    def acts_at_festival(self, festival, limit=10, offset=0):
        """
        get all acts at a festival.
        """
        return query_to_json("""
            select a.* 
            from mfc.acts a, mfc.acts_at_festival af
            where a.name=af.act and af.festival=%s
            limit %s offset %s
            """, [festival, limit, offset])
    
    @cherrypy.expose
    def festivals_for_act(self, act):
        """
        the other direction from acts_at_festival, find what festivals this act is at. Return festival names.
        """
        r = query_to_json("""
            select distinct(festival) from mfc.acts_at_festival where act = %s 
            """, [act])
        return [a['festival'] for a in r]

    @cherrypy.expose
    def genres_at_festival(self, festival):
        """
        get all genres at a festival.
        """
        r = query_to_json("""
            select distinct on (a.genre) genre 
            from mfc.acts a, mfc.acts_at_festival av
            where a.name=av.act and av.festival=%s
            and a.genre is not null and a.genre != ''
            """, [festival])
        ## this needs to be normalised.
        a = [a['genre'] for a in r]
        if not a:
            return []
        # split on , / ( ) and
        b = itertools.chain.from_iterable([re.split(r'/+|,|\(|\)| and ', b) for b in a])
        # remove a bunch of crap.
        b = set([c.replace('-',' ').replace('.', ''). replace('Music','').replace('Artist','').strip().title() for c in b])
        return sorted([a for a in b if a])

    #
    # venues
    #
    @cherrypy.expose
    def venue(self, ids):
        """
        get venues by id 
        """
        ids = to_tuple(ids)
        return query_to_json("""
            select * from mfc.venues where id in %s
            """, [ids])

    @cherrypy.expose
    def venue_at_festival(self, festival, limit=10, offset=0):
        """
        get venues by id or by festival
        """
        return query_to_json("""
            select * from mfc.venues where festival = %s limit %s offset %s
            """, [festival, limit, offset])

    #
    # Act at venue
    #
    @cherrypy.expose
    def act_at_venue(self, ids):
        """
        get acts_at_venues by id 
        """
        ids = to_tuple(ids)
        return query_to_json("""
            select * from mfc.acts_at_venues where id in %s
            """, [ids])

    @cherrypy.expose
    def act_at_venue_for_act(self, act):
        """
        get acts_at_venues by id 
        """
        r = {}
        for festival in self.festivals_for_act(act):
            a = query_to_json(
                """
                select venue, start_time from mfc.acts_at_venues where act = %s and festival = %s order by start_time
                """, [act, festival])
            if a:
                r[festival] = a
        return r
    # Plans
    #
    @cherrypy.expose
    def view_plan(self, plan_id):
        """ (permalink ish thingy?)
        view the plan, maybe cope with lineup changes?

        """       
        with get_db() as cur:
            cur.execute("select * from mfc.plans where id=%s", [plan_id])
            plan = cur.fetchall()
            cur.execute("""select a.* 
            from mfc.acts_at_venues a, mfc.plan_items p
            where p.plan = %s and act_at_venue = a.id""", [plan_id])
            return {"plan":plan, "items":cur.fetchall()}

    @cherrypy.expose
    def add_plan_item(self, plan, acts_at_venues, timestamp=None):
        """
        POST
        """
        acts_at_venues = to_tuple(acts_at_venues)
        with get_db() as cur:
            for act_at_venue in acts_at_venues:
                try:
                    cur.execute("insert into plan_items (%s, %s)", [plan, act_at_venue])
                except psycopg2.IntegrityError: #already inserted this
                    pass
            return True


    @cherrypy.expose
    def calculate_plan(self, festival, preferences):
        """
        * festival is the festival name
        * preferences is a JSON object with the preferences
          all keys are optional

        filter out any events that have an individual cost higher than the total cost.
        where day in 
        and cost < total_cost

        order by popularity / reviews / friends

        solve conflics by price, number of acts.
        """
        pass

    @cherrypy.expose
    def recommend_acts(self, festival, preferences=None, limit=10):
        """
        recommend limit acts depending on preferences. 

        returns the acts and all the acts_at_venues for the acts
        
        scoring function should look something like 

        a * num_planned + b * similarity + c * num_friends + d * reviews + e * google_popularity - f * cost

        where a-f are weighting factors.
        
        """
        with get_db() as cur:
            #check if we've got an times
            cur.execute("select act from mfc.acts_at_venues where festival = %s limit 1", [festival])
            if len(cur.fetchall()) == 0:
                times = False
            else:
                times = True
            
            score_query = "(COALESCE(bing_score, 0) / 1000 + COALESCE(likes,0) + COALESCE(followers,0)) rank"

            additional_where = ""
            if preferences.has_key('genres'):
                genres = to_tuple(preferences['genres'])
                genres = ['(%s)' % a.replace('&', '').replace(' ', ' & ') for a in genres]
                genres = ' | '.join(genres)
                score_query = "(ts_rank(to_tsvector(coalesce(genre,'')), to_tsquery(%s)) * 13000000 + COALESCE(likes,0) + COALESCE(followers,0)) as rank"
                score_query = cur.mogrify(score_query, [genres])
                additional_where = additional_where + cur.mogrify("""
                and genre @@ to_tsquery(%s)
                """, [genres])
                #print score_query

            if times and preferences.has_key('days'):
                days = to_tuple(preferences['days'])
                cur.execute("""
                select distinct on (name, rank) a.*, """ + score_query + """
                from mfc.acts_at_venues av, mfc.acts a 
                where av.act = a.name and
                    av.festival = %s
                and start_time::date in %s
                """ + additional_where + """
                order by rank desc
                limit %s
                """, [festival, days, limit])
            else:
                cur.execute("""
                select a.*, """ + score_query + """
                from mfc.acts_at_festival af, mfc.acts a 
                where af.act = a.name and
                    af.festival = %s
                """ + additional_where + """
                order by rank desc
                limit %s
                """, [festival, limit])
            #select the corresponding acts at venue for each acts
            acts = cur.fetchall()
            if cherrypy.response.current_lang != 'en':
                acts = add_translated_descriptions('acts', acts)
            for act in acts:
                cur.execute("""
                select * from mfc.acts_at_venues where act = %s and festival = %s order by start_time
                """, [act['name'], festival])
                act['act_at_venue'] = cur.fetchall()
        return acts

    @cherrypy.expose
    def optimal_times(self, festival, day, preferences=None):
        with get_db() as cur:
            #check if we've got an times
            cur.execute("select act from mfc.acts_at_venues where festival = %s limit 1", [festival])
            if len(cur.fetchall()) == 0:
                return False
            cur.execute("""
            select id, name, start_time, end_time, venue,
            (COALESCE(bing_score, 0) / 1000 + COALESCE(likes,0) + COALESCE(followers,0)) rank
            from mfc.acts_at_venues av, mfc.acts a 
            where av.act = a.name and av.festival = %s
            and start_time::date = %s::date
            order by start_time asc""", [festival, day])
            avs = cur.fetchall()
            # now we'll group in python because i'm not sure how to do this in sql...
            selected = []
            acts_selected = {}
            current_selected = None
            current_max = 0
            current_time = avs[0]['start_time']
            # score per minute? 
            for av in avs:
                if current_time.hour != av['start_time'].hour:
                    if selected:
                        if selected[-1]['end_time'] > current_selected['start_time']:
                            print 'prev act still on'
                        else:
                            selected.append(current_selected)
                            acts_selected[current_selected['name']] = acts_selected.get(current_selected['name'], 0) + 1
                    else:
                        selected.append(current_selected)
                        acts_selected[current_selected['name']] = acts_selected.get(current_selected['name'], 0) + 1
                    current_max = 0
                    # check if it's worth changing somehow... TODO
                    # penalty for venue change.

                score = av['rank'] / float((av['end_time'] - av['start_time']).seconds)
                if acts_selected.has_key(av['name']):
                    # penalty for seeing same act twice.
                    score = score / 10.0
                if score > current_max:
                    current_max = score
                    current_selected = av
                current_time = av['start_time']
            ##print repr(selected)
            #print 'total score', sum([b['rank'] for b in selected])
            #print 'total time in hours', sum([(b['end_time'] - b['start_time']).seconds for b in selected]) / 60 / 60.0
            selected = ', '.join(['#av_%s' % a['id'] for a in selected])
            return selected
    
    @cherrypy.expose
    def record_act_at_venue(self, act_at_venue, uid):
        cherrypy.response.headers['Cache-Control'] = 'max-age=0'
        with get_db() as cur:
            # delete existing for this act_at_venue 
            user = _get_user()
            # need to get festival to check the uid...
            cur.execute("SELECT festival FROM mfc.acts_at_venues where id = %s", [act_at_venue])
            festival = cur.fetchall()[0]['festival']

            if not uid_is_valid(user, uid, festival):
                print 'uid is invalid'
                return json.dumps(False)
            cur.execute("delete from mfc.attending_act_at_venue where id = %s and act_at_venue = %s", [uid, act_at_venue])
            #print cur.query, cur.rowcount
            if cur.rowcount == 0:
                # add if not already attending.
                cur.execute("""
                INSERT INTO mfc.attending_act_at_venue (id, act_at_venue, festival, day, username) 
                SELECT %s, %s, festival, start_time::date, %s
                FROM mfc.acts_at_venues where id = %s""", [uid, act_at_venue, user['email'] if user else None, act_at_venue])
        return self.similar_acts_on_day(act_at_venue)

    @cherrypy.expose
    def restore_schedule(self, festival, day, uid):
        with get_db() as cur:
            # delete existing for this act_at_venue 
            cur.execute("select act_at_venue from mfc.attending_act_at_venue where id = %s and festival = %s and day = %s", [uid, festival, day])
            #print cur.query, cur.rowcount
            return [a['act_at_venue'] for a in cur.fetchall()]

    @cherrypy.expose
    def similar_acts_on_day(self, act_at_venue):
        with get_db() as cur:
            # select this act's genere and process it to the right style for a TS query_to_json
            cur.execute("select genre from mfc.acts_at_venues v, mfc.acts a where id = %s and a.name = v.act", [act_at_venue])
            genre = cur.fetchall()[0]['genre']
            if not genre:
                return ''
            #print "#### genre =", genre
            # FIXME
            genres = re.split(r'/+|,|\(|\)| and ', genre)
            # remove a bunch of crap.
            genres = set([c.replace('-',' ').replace('.', ''). replace('Music','').replace('Artist','').strip().title() for c in genres])
            genres = ['%s' % a.replace('&', '').replace(' ', ' | ') for a in genres]
            genre = ' | '.join(genres).lower()
            #print "processed genre", genre
            #select matching acts based on day and genre.
            cur.execute("""
            select id, name from mfc.acts a, mfc.acts_at_venues v, (select start_time::date as day, festival from mfc.acts_at_venues where id = %s) as b where b.day =
            v.start_time::date and b.festival = v.festival and a.name = v.act and genre @@ %s::tsquery
            """, [act_at_venue, genre])
            similar = ', '.join(['#av_%s' % a['id'] for a in cur.fetchall()])
            return similar

    @cherrypy.expose
    def save_plan(self, plan_id, username):
        """
        FIXME 
        "you already have a plan for the festival, do you want to overwite it or save an alternative. Needs login with google/facebook via OAuth.
        """
        with get_db() as cur:
            cur.execute("update mfc.plans set username = %s where plan_id = %s", [username, plan_id])
        return True

    @cherrypy.expose
    def save_planned_acts(self, festival, username, locked_in_acts=None, recommended_acts=None, timestamp=None):
        """
        POST
        save acts given the list of recommended acts and locked in acts.
        one of locked_in_acts and recommend_acts must be non-empty
        deletes existing planned_acts.
        """
        if not any((locked_in_acts, recommended_acts)):
            return False
        locked_in_acts = locked_in_acts or '[]'
        recommended_acts = recommended_acts or '[]'
        # conn is commited after drops out of with, so don't need to do anything special in insert case here.
        with get_db() as cur:
            cur.execute("delete from mfc.planned_acts where festival=%s and username=%s", [festival, username])
            for act in json.loads(locked_in_acts):
                cur.execute("insert into mfc.planned_acts (festival, act, locked_in, username) values (%s, %s, %s, %s) ", [festival, act, True, username])
            for act in json.loads(recommended_acts):
                cur.execute("insert into mfc.planned_acts (festival, act, locked_in, username) values (%s, %s, %s, %s) ", [festival, act, False, username])
        return True

    @cherrypy.expose
    def plan_act(self, festival, username, act, locked_in=False, timestamp=None):
        """
        POST
        insert and ignore error if already in db.
        """
        with get_db() as cur:
            try:
                cur.execute("insert into mfc.planned_acts values (%s, %s, %s, %s)", [festival, act, locked_in, username])
            except psycopg2.IntegrityError: #already inserted this
                pass
        return True

    @cherrypy.expose
    def remove_act_from_plan(self, festival, username, act, timestamp=None):
        """
        POST
        delete act from planned_acts
        """
        with get_db() as cur:
            cur.execute("delete from mfc.planned_acts where festival = %s and act = %s and username = %s", [festival, act, username])
        return True

    #
    # Act at venue
    #
    @cherrypy.expose
    def get_planned_acts(self, festival, username):
        """
        get planned_acts for a festival for a user.
        """
        return query_to_json("""
            select act, locked_in from mfc.planned_acts where festival = %s and username = %s
            """, [festival, username])

    @cherrypy.expose
    def attend_festival(self, festival, username, timestamp=None):
        """
        POST
        insert and ignore error if already in db.
        """
        with get_db() as cur:
            try:
                cur.execute("insert into mfc.festival_attendence values (%s, %s)", [festival, username])
            except psycopg2.IntegrityError:
                pass

    @cherrypy.expose
    def unattend_festival(self, festival, username, timestamp=None):
        """
        POST
        delete from db.
        """
        with get_db() as cur:
            try:
                cur.execute("delete from mfc.festival_attendence where festival = %s and username = %s", [festival, username])
            except psycopg2.IntegrityError:
                pass

    @cherrypy.expose
    def user_is_attending(self, username, festival=None):
        """
        return festivals the user is attending. If festival is not None, return boolean if user is attending that festival.
        """
        with get_db() as cur:
            if festival:
                cur.execute("select * from mfc.festival_attendence where username = %s and festival = %s", [username, festival])
                return len(cur.fetchall()) == 1
            else:
                cur.execute("select festival from mfc.festival_attendence where username = %s", [username])
                return [a['festival'] for a in cur.fetchall()]

    # Invite
    # Share
    # User
    @cherrypy.expose
    def my_plans(self, username):
        """
        same as index + saved plans. Later share/reviews
        """
        with get_db() as cur:
            cur.execute("select * from mfc.plans where username=%s", [username])
            return cur.fetchall()

    @cherrypy.expose
    def popular_acts(self, limit=10, offset=0):
        """
        order acts by bing, likes etc
        """
        with get_db() as cur:
            cur.execute("""
            select *
            from mfc.acts 
            order by (COALESCE(bing_score, 0) / 1000 + COALESCE(likes,0) + COALESCE(followers,0)) desc
            limit %s offset %s""", [limit, offset])
            r = cur.fetchall()
            if cherrypy.response.current_lang != 'en':
                r = add_translated_descriptions('acts', r)
            return r

    @cherrypy.expose
    def popular_acts_at_festival(self, festival=False, limit=10, offset=0):
        """
        order acts by bing, likes etc
        """
        with get_db() as cur:
            cur.execute("""
            select act.*
            from mfc.acts_at_festival af, mfc.acts a 
            where af.act = a.name and festival=%s
            order by (COALESCE(bing_score, 0) / 1000 + COALESCE(likes,0) + COALESCE(followers,0)) desc
            limit %s offset %s""", [limit, offset])
            r = cur.fetchall()
            if cherrypy.response.current_lang != 'en':
                r = add_translated_descriptions('acts', r)
            return r

    @cherrypy.expose
    def popular_festivals(self, limit=10, offset=0):
        """
        order festivals by bing, likes etc
        """
        with get_db() as cur:
            cur.execute("""
            select *
            from mfc.festivals 
            where (start_date > now() - interval '2 days' or end_date > now() - interval '2 day') and start_date < now() + interval '2 months'
            order by (COALESCE(bing_score, 0) / 1000 + COALESCE(likes,0) + COALESCE(followers,0)) desc
            limit %s offset %s""", [limit, offset])
            r = cur.fetchall()
            if cherrypy.response.current_lang != 'en':
                r = add_translated_descriptions('festivals', r)
            return r

def _get_user():
    #print "the environ", repr(cherrypy.request.wsgi_environ), '###########', cherrypy.request.wsgi_environ['beaker.get_session']()
    session = cherrypy.request.wsgi_environ['beaker.session']
    #print 'getting user', session
    if 'email' in session:
        return { 'fb_access_token' : session['fb_access_token'],
                 'fb_user_id' : session['fb_user_id'],
                 'fb_picture' : session.get('fb_picture'),
                 'full_name' : session['full_name'],
                 'email' : session['email']
               }
    return None

class Primary(object):

    backend = JsonBackend()
    def __init__(self, lang='en'):
        self.lang = lang

    @cherrypy.expose        
    def create_session(self, email, full_name, fb_user_id, fb_access_token, fb_picture):
        '''Create user session from facebook information'''
        self.backend.create_user(email, full_name, fb_user_id, fb_access_token)
        session = cherrypy.request.wsgi_environ['beaker.session']
        session['full_name'] = full_name
        session['email'] = email
        session['fb_access_token'] = fb_access_token
        session['fb_user_id'] = fb_user_id
        session['fb_picture'] = fb_picture
        
        session.save()

    def _render_template(self, filename, **kwargs):
        '''Set up each template with required data'''
        template = mylookup.get_template(filename)

        kwargs['current_user'] = _get_user()
        kwargs['lang'] = self.lang
        kwargs['_'] = _

        return template.render(**kwargs)

    @cherrypy.expose
    def index(self):
        """
        search festival lineups, with a list of the most popular festivals
        "festival you're going to doesn't have it's lineup listed? 
        """
        cherrypy.response.headers['Cache-Control'] = 'max-age=0'
        get_lang(self.lang)
        location = geoip.record_by_addr(cherrypy.request.headers.get("X-Forwarded-For") or cherrypy.request.remote.ip)
        nearby_festivals = []

        if location:
            nearby_festivals = self.backend.list_festivals(location['latitude'], location['longitude'])

        return self._render_template('index.html',
                regions=['AU', 'DE'],
                featured_festivals = [{'name':'Coachella Weekend 1'}, {'name':'Byron Bay Bluesfest 2012'}],
                nearby_festivals = nearby_festivals,
                festivals = self.backend.popular_festivals(30),
                acts = self.backend.popular_acts(30))

    @cherrypy.expose
    def by_country(self, country=None):
        get_lang(self.lang)

        if country:
            country = pretty_param(country)
            return self._render_template('list_festivals_from_country.html',
                country = country,
                festivals = self.backend.festivals_from_country(country))
        else:
            return self._render_template('list_countries.html',
                    countries = self.backend.festival_countries())

    @cherrypy.expose
    def festival(self, festival):
        get_lang(self.lang)
        festival = pretty_param(festival)
        acts = self.backend.acts_at_festival(festival, limit='999999')
        popular_acts = [item['name'] for item in self.backend.recommend_acts(festival, {})]
        user = _get_user()
        user_is_attending = False
        if user:
            user_is_attending = self.backend.user_is_attending(user['email'], festival)

        return self._render_template('festival.html',
                festival = self.backend.festival(festival)[0],
                user_is_attending = user_is_attending,
                acts_at_festival = acts,
                popular_acts = popular_acts)
    
    @cherrypy.expose
    def search_festivals(self, query, longitude=None, latitude=None, limit=30, offset=0):
        get_lang(self.lang)
        cherrypy.response.headers['Cache-Control'] = 'max-age=0'
        offset = int(offset)
        limit = int(limit)
        if not latitude:
            location = geoip.record_by_addr(cherrypy.request.headers.get("X-Forwarded-For") or cherrypy.request.remote.ip)
            if location:
                latitude = location['latitude']
                longitude = location['longitude']
            next_page = {'query':query, 'offset':str(offset+limit)}
            prev_page = {'query':query, 'offset':str(offset-limit)}

        else:
            longitude, latitude = float(longitude), float(latitude)
            next_page = {'query':query, 'longitude':longitude, 'latitude':longitude, 'offset':str(offset+limit)}
            prev_page = {'query':query, 'longitude':longitude, 'latitude':longitude, 'offset':str(offset-limit)}

        if offset != 0:
            prev_page = cherrypy.url(qs=urllib.urlencode(prev_page))
        else:
            prev_page = None
        festivals = self.backend.search_festivals(query, latitude, longitude, limit, offset)
        if len(festivals) < limit:
            next_page = None
        else:
            next_page = cherrypy.url(qs=urllib.urlencode(next_page))

        return self._render_template('search_festivals.html',
                festivals = self.backend.search_festivals(query, latitude, longitude, limit, offset),
                next_page = next_page,
                prev_page = prev_page)

    @cherrypy.expose
    def act(self, act):
        get_lang(self.lang)
        act = str(pretty_param(act))

        return self._render_template('act.html',
                    act = self.backend.act(act)[0],
                    festivals = self.backend.festivals_for_act(act),
                    act_at_venue = self.backend.act_at_venue_for_act(act), max_eyes=MAX_EYES)

    @cherrypy.expose
    def recommend_acts(self, festival):
        """
        set preferences for recommendations.
        """
        get_lang(self.lang)
        festival = pretty_param(festival)
        genres = self.backend.genres_at_festival(festival)

        return self._render_template('recommend_acts.html',
                genres = genres,
                festival = festival,
                days = self.backend.festival_days(festival))

    @cherrypy.expose
    def recommended_acts(self, festival, **kwargs):
        get_lang(self.lang)

        festival = pretty_param(festival)
        acts = self.backend.recommend_acts(festival, preferences=kwargs)

        return self._render_template('recommended_acts.html',
                    acts = acts,
                    festival = festival)

    @cherrypy.expose
    def schedule(self, festival, day, uid=None, **kwargs):
        get_lang(self.lang)
        cherrypy.response.headers['Cache-Control'] = 'max-age=0'
        festival = pretty_param(festival)

        def get_new_uid(user):
            s = Signer(SECRET_SIGN_KEY)
            with get_db() as cur:
                cur.execute("insert into mfc.schedules (username, festival) values (%s, %s) returning id", [user['email'] if user else None, festival])
                uid = cur.fetchall()[0]['id']
            # cookie is uid hashed with our private key
            cookie = cherrypy.response.cookie
            cookie_name = 'mfc_sch'+str(uid)
            cookie[cookie_name] = s.sign(str(uid))
            cookie[cookie_name]['path'] = '/'
            cookie[cookie_name]['max-age'] = 3600
            cookie[cookie_name]['version'] = 1
            return uid
        
        user = _get_user()
        #if uid is not valid for this user/cookie set read_only = True
        if uid:
            read_only = not uid_is_valid(user, uid, festival)
        else:
            read_only = False
            if user:
                with get_db() as cur:
                    cur.execute("select id from mfc.schedules where username = %s and festival = %s", [user['email'], festival])
                    r = cur.fetchall()
                if r:
                    uid = r[0]['id']
                else:
                    uid = get_new_uid(user)
            else:
                uid = get_new_uid(user)
            raise cherrypy.HTTPRedirect(cherrypy.url(qs=urllib.urlencode({'uid':uid, 'day':day})))
        #acts = self.backend.recommend_acts(festival, preferences=kwargs)
        selected_acts = self.backend.restore_schedule(festival, day, uid)
        with get_db() as cur:
            cur.execute("""
            select %s::date - interval '1 day' as yesterday, 
                start_date::date < %s y_is, 
                end_date::date > %s t_is, 
                %s::date + interval '1 day' as tomorrow 
            from mfc.festivals where name = %s""", [day, day, day, day, festival])
            dates = cur.fetchall()[0]

        yesterday = False
        tomorrow = False
        if dates['y_is']:
            yesterday = cherrypy.url(qs=urllib.urlencode({'uid':uid, 'day':dates['yesterday']}))
        if dates['t_is']:
            tomorrow = cherrypy.url(qs=urllib.urlencode({'uid':uid, 'day':dates['tomorrow']}))
        new_schedule = cherrypy.url(qs=urllib.urlencode({'day':day}))

        return self._render_template('schedule.html',
                    all_acts = self.backend.festival_acts_by_day(festival, day),
                    acts_at_venues = self.backend.acts_by_venue_per_day(festival, day),
                    start_time = self.backend.festival_first_act_time(festival, day),
                    festival = festival, current_day = day, selected_acts = selected_acts, 
                    read_only = read_only, uid=uid, 
                    yesterday=yesterday, 
                    tomorrow = tomorrow, new_schedule = new_schedule)

    @cherrypy.expose
    def schedule_modal_content(self, act):
        get_lang(self.lang)
        act = str(pretty_param(act))

        return self._render_template('act_modal.html',
                    act = self.backend.act(act)[0])

    @cherrypy.expose
    def logout(self):
        cherrypy.response.headers['Cache-Control'] = 'max-age=0'
        session = cherrypy.request.wsgi_environ['beaker.session']
        session.delete()
        raise cherrypy.HTTPRedirect('/')
        
    @cherrypy.expose
    def choose_language(self):
        get_lang(self.lang)
        with get_db() as cur:
            cur.execute("select lang from mfc.descriptions group by lang order by count(*) desc")
            languages = cur.fetchall()

        for row in languages:
            try:
                loc = babel.Locale(row['lang'])
                if loc.display_name:
                    row['display_name'] = loc.display_name.title()
                else:
                    row['display_name'] = loc.english_name.title()
            except babel.UnknownLocaleError:
                row['display_name'] = row['lang']

        return self._render_template('choose_language.html',
                        languages = languages)

class Root(Primary):
    def __init__(self, langs):
        Primary.__init__(self)
        for lang in langs:
            setattr(self, lang, Primary(lang))

#we are in standalone mode
current_dir = os.path.dirname(os.path.abspath(__file__))
cherrypy.config['tools.json_out.handler'] = jsonify_date

def setup_redis_session(app):
    redis_pool = redis.ConnectionPool(host='localhost', port=6379, db=0)
    return SessionMiddleware(app, type="redis", url="localhost:6379", key="musicfilmcomedy", connection_pool=redis_pool)
    #return SessionMiddleware(app, type="file", data_dir='/tmp/cache/data', lock_dir ='/tmp/cache/lock')
    #return SessionMiddleware(app)

application = cherrypy.Application(Root(get_all_langs()), '', config='musicfilmcomedy.conf')
application.wsgiapp.pipeline.append(('beaker',  setup_redis_session))
if __name__ == '__main__':
    cherrypy.quickstart(application, '', config='musicfilmcomedy.conf')
