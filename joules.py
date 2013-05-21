from google.appengine.api.labs import taskqueue
from google.appengine.ext import webapp
from google.appengine.ext.webapp import util
from google.appengine.ext import db
from datetime import datetime
from time import mktime
import urllib
import re
import sys

class foobar(webapp.RequestHandler):
    def get(self):
        query = Stat.all()
        query.filter('camper =', 'blue').order('-timestamp')
        results = query.fetch(1)
        self.response.out.write(results[0].camper + ' / ' + str(results[0].joules) + ' / ' + str(results[0].timestamp))

class Stat(db.Model):
    camper = db.StringProperty(required=True)
    joules = db.IntegerProperty()
    timestamp = db.DateTimeProperty(required=True)
    
class Scrape(webapp.RequestHandler):
    def get(self):
        scrapepattern = re.compile('<td class="views-field views-field-name">\n.*>(.*)</a>[ ]*</td>\n[ ]*<td class="views-field views-field-points active">\n[ ]*([0-9]*)[ ]*</td>')
        readbuffer = ""
        input = urllib.urlopen('http://barcampmilwaukee.org/joules')
        readbuffer = input.read()
        listoftuples = scrapepattern.findall(readbuffer)
        for campername, joules in listoftuples:
            taskqueue.add(url='/tasks/check', params={'campername':campername,'joules':joules}, method='GET')
            
class CheckIfExists(webapp.RequestHandler):
    def get(self):
        campername = self.request.get('campername')
        joules = int(self.request.get('joules'))
        qmax = Stat.all()
        qmax.filter('camper =', campername).order('-timestamp')
        max = qmax.fetch(1)
        if not max or joules != max[0].joules:
            #alreadyexists = db.GqlQuery('SELECT * FROM Stat WHERE camper = :1 AND joules =:2',campername,joules).get()
            #if not alreadyexists:
            taskqueue.add(url='/tasks/store', params={'campername':campername,'joules':joules}, method='GET')

class StoreNewData(webapp.RequestHandler):
    def get(self):
        campername = self.request.get('campername')
        joules =  self.request.get('joules')
        timestamp = datetime.now()
        s = Stat(camper=campername,joules=int(joules),timestamp=timestamp)
        s.put()

class Json(webapp.RequestHandler):
    def get(self):
        campername = self.request.get('campername')
        if not campername: campername = 'mikeputnam'
        stats = db.GqlQuery('SELECT * FROM Stat WHERE camper = :1 ORDER BY timestamp',campername)
        outstring = '{"data": ['
        for stat in stats:
            t = stat.timestamp
            outstring +=  '[' + str(mktime(t.timetuple())) + ',' + str(stat.joules) + '],'
        outstring = outstring[:-1] + ']}'
        self.response.out.write(outstring)

class JsonCamperList(webapp.RequestHandler):
    def get(self):
        unique_campers = getcamperlist()
        sorted_unique_campers = sorted(unique_campers, key=unicode.lower)
        outstring = '{"camperlist": ['
        for camper in sorted_unique_campers:
            outstring += '"' + camper + '",'
        outstring = outstring[:-1] + ']}'
        self.response.out.write(outstring)

def getcamperlist():
    camperlist = []
    allstats = db.GqlQuery('SELECT * FROM Stat')
    for astat in allstats:
        camperlist.append(astat.camper)
    unique_campers = set(camperlist)
    return list(unique_campers)
    
class Cleanup(webapp.RequestHandler):
    def get(self):
        unique_campers = getcamperlist() 
        for camper in unique_campers:
            taskqueue.add(url='/tasks/cleanupworker', params={'camper':camper}, method='GET')
 
class CleanupWorker(webapp.RequestHandler):
    def get(self):
        blist = []
        camper = self.request.get('camper')
        camperstats = db.GqlQuery('SELECT * FROM Stat WHERE camper = :1 ORDER BY timestamp',camper)
        for camperstat in camperstats:
            blist.append(camperstat.joules)
        joulelist = set(blist)
        for jouleamt in joulelist:
            joulestats = db.GqlQuery('SELECT * FROM Stat WHERE camper = :1 and joules = :2 ORDER BY timestamp LIMIT 1',camper,jouleamt)
            for eachjouleamt in joulestats:
                deletestats = db.GqlQuery('SELECT * FROM Stat WHERE camper = :1 and joules = :2 and timestamp > :3 ',eachjouleamt.camper,eachjouleamt.joules,eachjouleamt.timestamp)
                for foo in deletestats: 
                    thekey = foo.key()
                    taskqueue.add(url='/tasks/deletestat', params={'key':thekey}, method='GET')

class DeleteStat(webapp.RequestHandler):
    def get(self):
        key = self.request.get('key')
        d = db.get(db.Key(key))
        d.delete()

def main():
    application = webapp.WSGIApplication([
        ('/foobar', foobar),
        ('/scrape', Scrape),
        ('/tasks/check', CheckIfExists),
        ('/tasks/store', StoreNewData),
        ('/tasks/deletestat', DeleteStat),
        ('/json', Json),
        ('/jsoncamperlist', JsonCamperList),
        ('/cleanup', Cleanup),
        ('/tasks/cleanupworker', CleanupWorker)
    ], debug=True)
    util.run_wsgi_app(application)

if __name__ == '__main__':
    main()
