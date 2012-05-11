import apesmit
import psycopg2
import psycopg2.extensions
import urllib2
psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)
conn = psycopg2.connect("dbname=musicfilmcomedy")
cur = conn.cursor()
url = 'http://www.musicfilmcomedy.com'
sm=apesmit.Sitemap(changefreq='weekly')

languages = {"arabic": "ar", "czech": "cs","danish": "da",
"german": "de","estonian": "et","finnish": "fi",
"french": "fr","dutch": "nl","greek": "el","hebrew": "he","hungarian": "hu","indonesian": "id",
"italian": "it","japanese": "ja","korean": "ko","lithuanian":"lt",
"latvian": "lv","norwegian": "no","polish": "pl","portuguese": "pt","romanian": "ro","spanish": "es","russian": "ru",
"slovak": "sk","slovene": "sl","swedish": "sv","thai": "th","turkish": "tr","ukranian": "uk","vietnamese": "vi","simplified chinese": "zh"}


def quote(a):
    #return urllib2.quote(a.decode('utf-8'))
    print repr(urllib2.quote(a.encode("utf-8")))
    #print repr(a.decode("utf-8"))
    return urllib2.quote(a.encode("utf-8"))
    #return a.encode("utf-8")
# all translated descriptions:
cur.execute("select lang, key from mfc.descriptions where feature = 'acts' and col = 'description' order by key;")
acts = cur.fetchall()
for act in acts:
    sm.add(url+'/%s/act/%s' % (act[0], quote(act[1].replace(' ', '_'))), changefreq='weekly', priority=0.5, lastmod='today')

cur.execute("select name from mfc.acts")
acts = cur.fetchall()
for act in acts:
    sm.add(url+'/act/%s' % quote(act[0].replace(' ', '_')), changefreq='weekly', priority=0.5, lastmod='today')


cur.execute("select lang, key from mfc.descriptions where feature = 'festivals' and col = 'description' order by key;")
acts = cur.fetchall()
for act in acts:
    sm.add(url+'/%s/festival/%s' % (act[0], quote(act[1].replace(' ', '_'))), changefreq='weekly', priority=0.9, lastmod='today')

cur.execute("select name, status from mfc.festivals")
acts = cur.fetchall()
for act in acts:
    sm.add(url+'/festival/%s' % quote(act[0].replace(' ', '_')), changefreq='weekly', priority=0.9, lastmod='today')
    if act[1] != 'unknown':
        sm.add(url+'/recommend_acts/%s' % quote(act[0].replace(' ', '_')), changefreq='monthly', priority=0.7, lastmod='today')
        sm.add(url+'/recommended_acts/%s' % quote(act[0].replace(' ', '_')), changefreq='monthly', priority=0.4, lastmod='today')
sm.add(url, changefreq='daily', priority=1, lastmod='today')
for lang in languages.values():
    sm.add(url+'/'+lang+'/', changefreq='daily', priority=1, lastmod='today')

#sm.add(url+'/, changefreq='daily', priority=1, lastmod='today')

with open('sitemap.xml', 'w') as out:
    sm.write(out)
