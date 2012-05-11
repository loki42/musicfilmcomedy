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
import bingtrans
import polib
import os,sys

BING_KEY = 'AE4F2D9144A988C235A23DF694F664D9357B2916'
languages = {"arabic": "ar", "czech": "cs","danish": "da",
"german": "de","english": "en","estonian": "et","finnish": "fi",
"french": "fr","dutch": "nl","greek": "el","hebrew": "he","hungarian": "hu","indonesian": "id",
"italian": "it","japanese": "ja","korean": "ko","lithuanian":"lt",
"latvian": "lv","norwegian": "no","polish": "pl","portuguese": "pt","romanian": "ro","spanish": "es","russian": "ru",
"slovak": "sk","slovene": "sl","swedish": "sv","thai": "th","turkish": "tr","ukranian": "uk","vietnamese": "vi","simplified chinese": "zh-CHS"} #,"traditional chinese": "zh-CHT"}

#languages = {"simplified chinese": "zh-CHS"}
bingtrans.set_app_id(BING_KEY)

for lang in languages.values():
    lang = lang[:2]
    ##return false;os.system("pybabel init -D musicfilmcomedy -i locale/musicfilmcomedy.pot -d locale/ -l "+lang)

    #return False
    po = polib.pofile('locale/%s/LC_MESSAGES/musicfilmcomedy.po' % lang)
    for a in po.untranslated_entries():
        print a.msgid
        a.msgstr = bingtrans.translate(a.msgid, 'en', lang if lang != 'zh' else 'zh-CHS').replace("% s", "%s")
        print a.msgstr
    po.save('locale/%s/LC_MESSAGES/musicfilmcomedy.po' % lang)
    po.save_as_mofile('locale/%s/LC_MESSAGES/musicfilmcomedy.mo' % lang)
