# - coding: utf-8 -

# Copyright (C) 2007 Patryk Zawadzki <patrys at pld-linux.org>
# Copyright (C) 2008, 2010 Toms Bauģis <toms.baugis at gmail.com>

# This file is part of Project Hamster.

# Project Hamster is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# Project Hamster is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with Project Hamster.  If not, see <http://www.gnu.org/licenses/>.

import logging
from configuration import conf
import gobject
import re
import dbus, dbus.mainloop.glib
import json
from lib import rt
from lib import redmine

try:
    import evolution
    from evolution import ecal
except:
    evolution = None
    
class ActivitiesSource(gobject.GObject):
    def __init__(self):
        logging.debug('external init')
        gobject.GObject.__init__(self)
        self.source = conf.get("activities_source")
        self.__gtg_connection = None

        if self.source == "evo" and not evolution:
            self.source == "" # on failure pretend that there is no evolution
        elif self.source == "gtg":
            gobject.GObject.__init__(self)
            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        elif self.source == "rt":
            self.rt_url = conf.get("rt_url")
            self.rt_user = conf.get("rt_user")
            self.rt_pass = conf.get("rt_pass")
            self.rt_query = conf.get("rt_query")
            self.rt_category = conf.get("rt_category_field")
            self.rt_category_fallback = conf.get("rt_category_field_fallback")
            if self.rt_url and self.rt_user and self.rt_pass:
                try:
                    self.tracker = rt.Rt(self.rt_url, self.rt_user, self.rt_pass)
                    if not self.tracker.login():
                        self.source = ""
                except Exception as e:
                    logging.warn('rt login failed: '+str(e))
                    self.source = ""
            else:
                self.source = ""
        elif self.source == "redmine":
            self.rt_url = conf.get("rt_url")
            self.rt_user = conf.get("rt_user")
            self.rt_pass = conf.get("rt_pass")
            self.rt_category = conf.get("rt_category_field")
            self.rt_category_fallback = conf.get("rt_category_field_fallback")
            try:
                self.rt_query = json.loads(conf.get("rt_query"))
            except:
                self.rt_query = ({})
            if self.rt_url and self.rt_user and self.rt_pass:
                try:
                    self.tracker = redmine.Redmine(self.rt_url, auth=(self.rt_user,self.rt_pass))
                    if not self.tracker:
                        self.source = ""
                except:
                    self.source = ""
            else:
                self.source = ""
        
    def get_activities(self, query = None):
        if not self.source:
            return []

        if self.source == "evo":
            return [activity for activity in get_eds_tasks()
                         if query is None or activity['name'].startswith(query)]
        elif self.source == "rt":
            activities = self.__extract_from_rt(query, self.rt_query)
            direct_ticket = None
            if query and re.match("^[0-9]+$", query):
                ticket = self.tracker.get_ticket(query)
                if ticket:
                    direct_ticket = self.__extract_activity_from_ticket(ticket)
            if direct_ticket:
                activities.append(direct_ticket)
            if len(activities) <= 2 and not direct_ticket and len(query) > 4:
                li = query.split(' ')
                rt_query = " AND ".join(["(Subject LIKE '%s' OR Owner='%s')" % (q, q) for q in li]) + " AND (Status='new' OR Status='open')"
                #logging.warn(rt_query)
                third_activities = self.__extract_from_rt(query, rt_query, False)
                if activities and third_activities:
                    activities.append({"name": "---------------------", "category": "other open"})
                activities.extend(third_activities)
            return activities
        elif self.source == "redmine":
            activities = self.__extract_from_redmine(query, self.rt_query)
            direct_issue = None
            if query and re.match("^[0-9]+$", query):
                issue = self.tracker.getIssue(query)
                if issue:
                    direct_issue = self.__extract_activity_from_issue(issue)
            if direct_issue:
                activities.append(direct_issue)
            if len(activities) <= 2 and not direct_issue and len(query) > 4:
                rt_query = ({'status_id': 'open', 'subject': query})
                #logging.warn(rt_query)
                third_activities = self.__extract_from_redmine(query, rt_query)
                if activities and third_activities:
                    activities.append({"name": "---------------------", "category": "other open"})
                activities.extend(third_activities)
            return activities
        elif self.source == "gtg":
            conn = self.__get_gtg_connection()
            if not conn:
                return []

            activities = []

            tasks = []
            try:
                tasks = conn.GetTasks()
            except dbus.exceptions.DBusException:  #TODO too lame to figure out how to connect to the disconnect signal
                self.__gtg_connection = None
                return self.get_activities(query) # reconnect


            for task in tasks:
                if query is None or task['title'].lower().startswith(query):
                    name = task['title']
                    if len(task['tags']):
                        name = "%s, %s" % (name, " ".join([tag.replace("@", "#") for tag in task['tags']]))

                    activities.append({"name": name, "category": ""})

            return activities
        
    def get_ticket_category(self, ticket_id):
        if not self.source:
            return ""

        if self.source == "rt":
            ticket = self.tracker.get_ticket(ticket_id)
            return self.__extract_cat_from_ticket(ticket)
        else:
            return ""
    
    def __extract_activity_from_ticket(self, ticket):
        #activity = {}
        ticket_id = ticket['id']
        #logging.warn(ticket)
        if 'ticket/' in ticket_id:
            ticket_id = ticket_id[7:]
        ticket['name'] = '#'+ticket_id+': '+ticket['Subject'].replace(",", " ")
        if 'Owner' in ticket and ticket['Owner']!=self.rt_user:
            ticket['name'] += " (%s)" % ticket['Owner'] 
        ticket['category'] = self.__extract_cat_from_ticket(ticket)
        ticket['rt_id']=ticket_id;
        return ticket
    
    def __extract_activity_from_issue(self, issue):
        activity = {}
        issue_id = issue.id
        activity['name'] = '#'+str(issue_id)+': '+issue.subject
        activity['rt_id']=issue_id;
        activity['category']="";
        return activity

    def __extract_from_rt(self, query = None, rt_query = None, checkName = True):
        activities = []
        results = self.tracker.search_simple(rt_query)
        for ticket in results:
            activity = self.__extract_activity_from_ticket(ticket)
            if query is None or not checkName or all(item in activity['name'].lower() for item in query.lower().split(' ')):
                activities.append(activity)
        return activities
        
    def __extract_from_redmine(self, query = None, rt_query = None):
        activities = []
        results = self.tracker.getIssues(rt_query)
        for issue in results:
            activity = self.__extract_activity_from_issue(issue)
            if query is None or all(item in activity['name'].lower() for item in query.lower().split(' ')):
                activities.append(activity)
        return activities
        
    def __extract_cat_from_ticket(self, ticket):
        category = "RT"
        if 'Queue' in ticket:
            category = ticket['Queue']
        if self.rt_category_fallback in ticket and ticket[self.rt_category_fallback]:
            category = ticket[self.rt_category_fallback].split('/')[0]
        if self.rt_category in ticket and ticket[self.rt_category]:
            category = ticket[self.rt_category]
#        owner = None
#        if 'Owner' in ticket:
#            owner = ticket['Owner']
#        if owner and owner!=self.rt_user:
#            category += ":"+owner
        return category

    def __get_gtg_connection(self):
        bus = dbus.SessionBus()
        if self.__gtg_connection and bus.name_has_owner("org.gnome.GTG"):
            return self.__gtg_connection

        if bus.name_has_owner("org.gnome.GTG"):
            self.__gtg_connection = dbus.Interface(bus.get_object('org.gnome.GTG', '/org/gnome/GTG'),
                                                   dbus_interface='org.gnome.GTG')
            return self.__gtg_connection
        else:
            return None



def get_eds_tasks():
    try:
        sources = ecal.list_task_sources()
        tasks = []
        if not sources:
            # BUG - http://bugzilla.gnome.org/show_bug.cgi?id=546825
            sources = [('default', 'default')]

        for source in sources:
            category = source[0]

            data = ecal.open_calendar_source(source[1], ecal.CAL_SOURCE_TYPE_TODO)
            if data:
                for task in data.get_all_objects():
                    if task.get_status() in [ecal.ICAL_STATUS_NONE, ecal.ICAL_STATUS_INPROCESS]:
                        tasks.append({'name': task.get_summary(), 'category' : category})
        return tasks
    except Exception, e:
        logging.warn(e)
        return []
