# Copyright 2011, Dan Gindikin <dgindikin@gmail.com>
# Copyright 2012, Jono Finger <jono@foodnotblogs.com>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.

import time
import sys
import math
import cairo
import re
import copy
import platform

from gi.repository import Gtk, GdkPixbuf, Gdk, GtkSource, Gio, Gedit, GObject

version = "0.2 beta - gtk3"


def document_lines(document):
  if not document:
    return None

  return document.get_property('text').split('\n')

def visible_lines_top_bottom(view):
  rect = view.get_visible_rect()
  topiter = view.get_line_at_y(rect.y)[0]
  botiter = view.get_line_at_y(rect.y+rect.height)[0]
  return topiter.get_line(), botiter.get_line()
  
def dark(r,g,b):
  "return whether the color is light or dark"
  if r+g+b < 1.5:
    return True
  else:
    return False
    
def darken(fraction,r,g,b):
  return r-fraction*r,g-fraction*g,b-fraction*b
  
def lighten(fraction,r,g,b):
  return r+(1-r)*fraction,g+(1-g)*fraction,b+(1-b)*fraction

def queue_refresh(textmapview):
#  print ('queue_refresh ' + str(textmapview.darea))
#  print ('queue_refresh ' + str(textmapview.darea.get_window()))
  try:
    win = textmapview.darea.get_window()
  except AttributeError:
    win = textmapview.darea.window

#  textmapview.darea.queue_draw()
  textmapview.queue_draw()

#  if win:
#    print ('queue_refresh2')
#    textmapview.darea.queue_draw_area(0,0,win.get_width(),win.get_height())
    
def str2rgb(s):
  assert s.startswith('#') and len(s)==7,('not a color string',s)
  r = int(s[1:3],16)/256.
  g = int(s[3:5],16)/256.
  b = int(s[5:7],16)/256.
  return r,g,b


class TextmapWindow(Gtk.VBox):
  def __init__(me, geditwindow):
    Gtk.VBox.__init__(me)
    
    print ('init window')

    me.mapWidth = 200

    me.geditwindow = geditwindow

    me.geditwindow.connect_after("active-tab-changed", me.active_tab_changed)
#    me.geditwindow.connect_after("active-tab-state-changed", me.active_tab_state_changed)
    me.geditwindow.connect_after("tab-added", me.tab_added)

#    me.geditwindow.connect_after("size-request", me.size_request)

    me.textmapviews = {}

#    me.pack_start(geditwindow, True, True, 0)  # can we remove this?

    me.show_all()
    

  def tab_added(me, window, tab):
    print ('window tab-added ')
    me.textmapviews[tab] = TextmapView(tab.get_view(), tab.get_document())


  def active_tab_changed(me, window, tab):
    print ('window active-tab-changed ')
#    me.textmapviews[tab].update_map_position()

  def size_request(me, requisition):
    print ('win size request')


class TextmapView(Gtk.VBox):
  def __init__(me, view, thisbuffer):
    Gtk.VBox.__init__(me)
    
    print ('init view')

    me.mapWidth = 200

    me.currentView = view
    me.currentBuffer = thisbuffer

    
    me.darea = Gtk.DrawingArea()

    me.connect('draw', me.draw)
    me.darea.connect("draw", me.draw)
    
    me.darea.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
    me.darea.connect("button-press-event", me.button_press)
    me.darea.connect("scroll-event", me.on_darea_scroll_event)

    me.darea.add_events(Gdk.EventMask.POINTER_MOTION_MASK)
    me.darea.connect("motion-notify-event", me.on_darea_motion_notify_event)

    me.darea.set_size_request(200, 300)


    me.pack_start(me.darea, True, True, 0)  # can we remove this?
    me.currentView.add_child_in_window(me, Gtk.TextWindowType.RIGHT, 0, 0)


    me.show_all()

    me.topL = None
    me.botL = None
    me.scale = 4   # TODO: set this smartly somehow

    me.winHeight = 0
    me.winWidth = 0
    me.linePixelHeight = 0

    me.lines = None

    me.currentView.connect_after('map', me.on_map)
    me.currentBuffer.connect('changed', me.on_doc_changed)
    me.currentView.get_vadjustment().connect('value-changed', me.on_vadjustment_changed)
    # TODO: make sure value-changed is not conflicting with darea move events

#    me.currentView.connect('size-request', me.size_request)

  def on_map(me, arg):
    print ('map')
    me.update_map_position()

  def size_request(me, requisition):
    print ('view size-request')


  def update_map_position(me):

    hpos = 0

    hpos = me.currentView.get_window(Gtk.TextWindowType.TEXT).get_width() - me.mapWidth

    if me.currentView.get_window(Gtk.TextWindowType.LEFT):
      hpos += me.currentView.get_window(Gtk.TextWindowType.LEFT).get_width()

    me.currentView.move_child(me, hpos, 0)

    me.darea.set_size_request(me.mapWidth, me.currentView.get_window(Gtk.TextWindowType.TEXT).get_height());

    print ('hpos ' + str(hpos) + ' height ' + str(me.currentView.get_window(Gtk.TextWindowType.TEXT).get_height()))

  def on_doc_changed(me, buffer):
    me.lines = document_lines(me.currentBuffer)
    queue_refresh(me)

  def on_vadjustment_changed(me, adjustment):
    queue_refresh(me)

  def on_darea_motion_notify_event(me, widget, event):
    "used for clicking and dragging"

    if event.state & Gdk.ModifierType.BUTTON1_MASK:
      me.scroll_from_y_mouse_pos(event.y)
    
  def on_darea_scroll_event(me, widget, event):
    
    pagesize = 12 # TODO: match this to me.currentView.get_vadjustment().get_page_size()
    topL, botL = visible_lines_top_bottom(me.currentView)
    if event.direction == Gdk.ScrollDirection.UP and topL > pagesize:
      newI = topL - pagesize
    elif event.direction == Gdk.ScrollDirection.DOWN:
      newI = botL + pagesize
    else:
      return

    me.currentView.scroll_to_iter(me.currentBuffer.get_iter_at_line_index(newI,0),0,False,0,0)
    
    queue_refresh(me)
    
  def scroll_from_y_mouse_pos(me,y):

    me.currentView.scroll_to_iter(me.currentBuffer.get_iter_at_line_index(int((len(me.lines) + (me.botL - me.topL)) * y/me.winHeight),0),0,True,0,.5)
    queue_refresh(me)
    
  def button_press(me, widget, event):
    me.scroll_from_y_mouse_pos(event.y)
  
  def draw(me, widget, cr):

    if not me.currentBuffer or not me.currentView:   # nothing open yet
      return
    
    bg = (0,0,0)
    fg = (1,1,1)
    try:
      style = me.currentBuffer.get_style_scheme().get_style('text')
      if style is None: # there is a style scheme, but it does not specify default
        bg = (1,1,1)
        fg = (0,0,0)
      else:
        fg,bg = map(str2rgb, style.get_properties('foreground','background'))  
    except:
      pass  # probably an older version of gedit, no style schemes yet

    try:
      win = widget.get_window()
    except AttributeError:
      win = widget.window

    cr = win.cairo_create()

    me.winHeight = win.get_height()
    me.winWidth = win.get_width()

    cr.push_group()
    
    # draw the background
    cr.set_source_rgba(bg[0], bg[1], bg[2], 0.95)
    cr.move_to(0,0)
    cr.rectangle(0,0,me.winWidth,me.winHeight)
    cr.fill()
    cr.move_to(0,0)
    
    if not me.lines:
      return

    # draw the text
    cr.select_font_face('monospace', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    cr.set_font_size(me.scale)

    if me.linePixelHeight == 0:
      me.linePixelHeight = cr.text_extents("L")[3] # height # TODO: make this more global

    me.topL, me.botL = visible_lines_top_bottom(me.currentView)

    if dark(*fg):
      faded_fg = lighten(.5,*fg)
    else:
      faded_fg = darken(.5,*fg)
    
    cr.set_source_rgb(*fg)

    textViewLines = int(me.winHeight/me.linePixelHeight)

    firstLine = me.topL - int((textViewLines - (me.botL - me.topL)) * float(me.topL)/float(len(me.lines)))
    if firstLine < 0: firstLine = 0

    lastLine =  firstLine + textViewLines
    if lastLine > len(me.lines): lastLine = len(me.lines)

    sofarH = 0

    for i in range(firstLine, lastLine, 1):
      cr.show_text(me.lines[i])  
      sofarH += me.linePixelHeight
      cr.move_to(0, sofarH)

    cr.set_source(cr.pop_group())
    cr.rectangle(0,0,me.winWidth,me.winHeight)
    cr.fill()

    # draw the scrollbar
    topY = (me.topL - firstLine) * me.linePixelHeight
    if topY < 0: topY = 0
    botY = topY + me.linePixelHeight*(me.botL-me.topL)
    # TODO: handle case   if botY > ?

    cr.set_source_rgba(.3,.3,.3,.35)
    cr.rectangle(0,topY,me.winWidth,botY-topY)
    cr.fill()
    cr.stroke()


class TextmapWindowHelper:
  def __init__(me, plugin, window):
    me.window = window
    me.plugin = plugin

#    panel = me.window.get_side_panel()
#    image = Gtk.Image()
#    image.set_from_stock(Gtk.STOCK_DND_MULTIPLE, Gtk.IconSize.BUTTON)
    me.textmapview = TextmapWindow(me.window)
#    me.ui_id = panel.add_item(me.textmapview, "TextMap", "textMap", image)
    
#    me.panel = panel

  def deactivate(me):
    me.window = None
    me.plugin = None
    me.textmapview = None

  def update_ui(me):
    print ('update_ui')
    queue_refresh(me.textmapview)

class WindowActivatable(GObject.Object, Gedit.WindowActivatable):
  
  window = GObject.property(type=Gedit.Window)

  def __init__(self):
    GObject.Object.__init__(self)
    self._instances = {}    # TODO: instances?

  def do_activate(self):
    self._instances[self.window] = TextmapWindowHelper(self, self.window)

  def do_deactivate(self):
    if self.window in self._instances:
      self._instances[self.window].deactivate()

  def update_ui(self):
    if self.window in self._instances:
      self._instances[self.window].update_ui()
