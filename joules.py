from google.appengine.api.labs import taskqueue

from google.appengine.ext import webapp
from google.appengine.ext.webapp import util

from google.appengine.ext import db
from datetime import datetime
from time import mktime
from random import choice

import urllib
import re
import sys

class Stat(db.Model):
    camper = db.StringProperty(required=True)
    joules = db.IntegerProperty()
    timestamp = db.DateTimeProperty(required=True)
    
class MainHandler(webapp.RequestHandler):
    def get(self):
        thehtml = """
<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<html>
 <head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
    <title>v2.0</title>
    <link href="/stylesheets/layout.css" rel="stylesheet" type="text/css"></link>
    <!--[if IE]><script language="javascript" type="text/javascript" src="/js/excanvas.min.js"></script><![endif]-->
    <script language="javascript" type="text/javascript" src="/js/jquery.js"></script>
    <script language="javascript" type="text/javascript" src="/js/jquery.flot.js"></script>
 </head>
    <body>
    <h1>v2.0</h1>
    <div id="loading"><img src="/images/ajax-loader.gif" alt=""/>Loading data...</div>
    <div id="placeholder" style="width:600px;height:300px;"></div>
    

<script id="source">
$(function () {

    $.getJSON('/json', function(data) {
        for (var i = 0; i < data.data.length; ++i)
            data.data[i][0] = (data.data[i][0] * 1000) + (((60 * 60 * 1000) * 5) * -1);
            
        $.plot($("#placeholder"), [data], { 
            series: {
               lines: { show: true },
               points: { show: true }
            },
            grid: { 
                hoverable: true, 
                clickable: true 
            },
            xaxis: { 
                mode: "time",
                timeformat: "%m/%d %h:%M%p"
            } 
        });

        $('#loading').hide();

        function showTooltip(x, y, contents) {
            $('<div id="tooltip">' + contents + '</div>').css( {
                position: 'absolute',
                display: 'none',
                top: y + 5,
                left: x + 5,
                border: '1px solid #fdd',
                padding: '2px',
                'background-color': '#fee',
                opacity: 0.80
            }).appendTo("body").fadeIn(200);
        }

        var previousPoint = null;
        $("#placeholder").bind("plothover", function (event, pos, item) {
            if (item) {
                if (previousPoint != item.datapoint) {
                    previousPoint = item.datapoint;

                    $("#tooltip").remove();
                    var x = item.datapoint[0].toFixed(2),
                        y = item.datapoint[1].toFixed(2);

                    //showTooltip(item.pageX, item.pageY, item.series.label + " of " + x + " = " + y);
                    showTooltip(item.pageX,item.pageY, Math.floor(y) + " joules");
                }
            }
            else {
                $("#tooltip").remove();
                previousPoint = null;            
            }

        });
    }); //end getJSON
});
</script>

 </body>
</html>
        """

        self.response.out.write(thehtml)

class Scrape(webapp.RequestHandler):
    def get(self):
        self.response.out.write('/scrape called!')
        scrapepattern = re.compile('<td class="views-field views-field-name">\n.*>(.*)</a>[ ]*</td>\n[ ]*<td class="views-field views-field-points active">\n[ ]*([0-9]*)[ ]*</td>')
        readbuffer = ""
        input = urllib.urlopen('http://barcampmilwaukee.org/joules')
        readbuffer = input.read()
        listoftuples = scrapepattern.findall(readbuffer)
        #self.response.out.write(listoftuples)
        for campername, joules in listoftuples:
            taskqueue.add(url='/tasks/check', params={'campername':campername,'joules':joules}, method='GET')
            
class CheckIfExists(webapp.RequestHandler):
    def get(self):
        campername = self.request.get('campername')
        joules = int(self.request.get('joules'))
        alreadyexists = db.GqlQuery('SELECT * FROM Stat WHERE camper = :1 AND joules =:2',campername,joules).get()
        if not alreadyexists:
            self.response.out.write('submitting camper to /tasks/store queue: ' + campername + '=' + str(joules))
            taskqueue.add(url='/tasks/store', params={'campername':campername,'joules':joules}, method='GET')
        else:
            self.response.out.write('stat already exists. not storing: ' + campername + '=' + str(joules))

class StoreNewData(webapp.RequestHandler):
    def get(self):
        campername = self.request.get('campername')
        joules =  self.request.get('joules')
        timestamp = datetime.now()
        s = Stat(camper=campername,joules=int(joules),timestamp=timestamp)
        s.put()

class Json(webapp.RequestHandler):
    def get(self):
        stats = db.GqlQuery('SELECT * FROM Stat WHERE camper = :1 ORDER BY timestamp','raster')
        outstring = '{"data": ['
        for stat in stats:
            t = stat.timestamp
            outstring +=  '[' + str(mktime(t.timetuple())) + ',' + str(stat.joules) + '],'
        outstring = outstring[:-1] + ']}'
        self.response.out.write(outstring)

class Cleanup(webapp.RequestHandler):
    def get(self):
        camperlist = []
        allstats = db.GqlQuery('SELECT * FROM Stat')
        for astat in allstats:
            camperlist.append(astat.camper)
        unique_campers = set(camperlist)
        for camper in unique_campers:
            self.response.out.write('spawning cleanupworker for: ' + camper + '<br/>' )
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
                for pleh in deletestats: 
                    self.response.out.write(pleh.camper + ' ' + str(pleh.joules) + ' ' + str(pleh.timestamp) + '<br/>' )
                    thekey = pleh.key()
                    taskqueue.add(url='/tasks/deletestat', params={'key':thekey}, method='GET')

class DeleteStat(webapp.RequestHandler):
    def get(self):
        key = self.request.get('key')
        d = db.get(db.Key(key))
        d.delete()


def main():
    application = webapp.WSGIApplication([
        ('/', MainHandler),
        ('/scrape', Scrape),
        ('/tasks/check', CheckIfExists),
        ('/tasks/store', StoreNewData),
        ('/tasks/deletestat', DeleteStat),
        ('/json', Json),
        ('/cleanup', Cleanup),
        ('/tasks/cleanupworker', CleanupWorker)
    ], debug=True)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()
