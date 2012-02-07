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

# ------------------------------------------------------------------------------

class struct:pass

def document_lines(document):
  if not document:
    return None

  STR = document.get_property('text')
  lines = STR.split('\n')
  ans = []

  for i,each in enumerate(lines):

    x = struct()
    x.i = i
    x.raw = each

    ans.append(x)
  return ans

  
BUG_MASK = 0

BUG_CAIRO_MAC_FONT_REF  = 1
BUG_CAIRO_TEXT_EXTENTS  = 2
BUG_DOC_GET_SEARCH_TEXT = 4

if platform.system() == 'Darwin':
  BUG_MASK |= BUG_CAIRO_MAC_FONT_REF  # extra decref causes aborts, use less font ops

# major,minor,patch = Gedit.version
# if major<=2 and minor<28:
#   BUG_MASK |= BUG_CAIRO_TEXT_EXTENTS  # some reference problem
#   BUG_MASK |= BUG_DOC_GET_SEARCH_TEXT # missing INCREF then
  
def text_extents(str,cr):
  "code around bug in older cairo"
  
  # if BUG_MASK & BUG_CAIRO_TEXT_EXTENTS:  
  #   if str:
  #     x, y = cr.get_current_point()
  #     cr.move_to(0,-5)
  #     cr.show_text(str)
  #     nx,ny = cr.get_current_point()
  #     cr.move_to(x,y)
  #   else:
  #     nx = 0
  #     ny = 0

  #   #print repr(str),x,nx,y,ny
  #   ascent, descent, height, max_x_advance, max_y_advance = cr.font_extents()
  
  #   return nx, height
  
  # else:
  
  x_bearing, y_bearing, width, height, x_advance, y_advance = cr.text_extents(str)
  return width, height


# def downsample_lines2(lines, h, min_scale, max_scale):
#   n = len(lines)
  
#   # pick scale
#   for scale in range(max_scale,min_scale-1,-1): # 3,2,1
#     maxlines_ = h/(.85*scale)
#     if n < 2*maxlines_:
#       break
    
#   downsampled = False
  
#   return lines, scale, downsampled

def visible_lines_top_bottom(geditwin):
  view = geditwin.get_active_view()
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
  
def scrollbar(linePixelHeight, lines,topI,botI,w,h,cr, firstLine):

  "highlights where in the textmap we are scrolled to"

  topY = (topI - firstLine) * linePixelHeight
  if topY < 0: topY = 0
  botY = topY + linePixelHeight*(botI-topI)
  # TODO: handle case   if botY > ?

  cr.set_source_rgba(.3,.3,.3,.35)
  cr.rectangle(0,topY,w,botY-topY)
  cr.fill()
  cr.stroke()

        
def queue_refresh(textmapview):
  try:
    win = textmapview.darea.get_window()
  except AttributeError:
    win = textmapview.darea.window
  if win:
    textmapview.darea.queue_draw_area(0,0,win.get_width(),win.get_height())
    
def str2rgb(s):
  assert s.startswith('#') and len(s)==7,('not a color string',s)
  r = int(s[1:3],16)/256.
  g = int(s[3:5],16)/256.
  b = int(s[5:7],16)/256.
  return r,g,b
      
class TextmapView(Gtk.VBox):
  def __init__(me, geditwin):
    Gtk.VBox.__init__(me)
    
    me.geditwin = geditwin

    me.geditwin.connect("active-tab-changed", me.tab_changed)
    me.geditwin.connect("tab-added", me.tab_added)
    # TODO: handle other "active-tab-state-changed" like signals
    
    darea = Gtk.DrawingArea()
    darea.connect("draw", me.draw)
    
    darea.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
    darea.connect("button-press-event", me.button_press)
    darea.connect("scroll-event", me.on_darea_scroll_event)

    darea.add_events(Gdk.EventMask.POINTER_MOTION_MASK)
    darea.connect("motion-notify-event", me.on_darea_motion_notify_event)
    
    
    me.pack_start(darea, True, True, 0)

    me.connected = {}

    me.topL = None
    me.botL = None
    
    me.show_all()

    me.scale = 5

    me.darea = darea

    me.winHeight = 0
    me.winWidth = 0
    me.linePixelHeight = 0

    me.currentDoc = None
    me.currentView = None
    
     #'''
     #   gtk.gdk.SCROLL_UP, 
     #  gtk.gdk.SCROLL_DOWN, 
     #  gtk.gdk.SCROLL_LEFT, 
     #  gtk.gdk.SCROLL_RIGHT
   #
     #Example:
   #
     #  def on_button_scroll_event(button, event):
     #    if event.direction == gtk.gdk.SCROLL_UP:
     #       print "You scrolled up"
     #       
     #event = gtk.gdk.Event(gtk.gdk.EXPOSE)
     #
     #      def motion_notify(ruler, event):
     #          return ruler.emit("motion_notify_event", event)
     #      self.area.connect_object("motion_notify_event", motion_notify,
     #                               self.hruler)
     #      self.area.connect_object("motion_notify_event", motion_notify,
     #                               self.vruler)
     #'''
  
  def tab_added(me, window, tab):
    me.currentView = tab.get_view()
    
    me.currentDoc = tab.get_document()

    me.currentDoc.connect('changed', me.on_doc_changed)
    me.currentView.connect('scroll-event', me.on_scroll_event)

    print ('tab_added')

  def tab_changed(me, window, event):
    # TODO: handle when there are no docs
    me.currentView = me.geditwin.get_active_view()
    me.currentDoc = me.geditwin.get_active_tab().get_document()

    me.lines = document_lines(me.currentDoc)
    print ('tab_changed lines ' + str(len(me.lines)))
    queue_refresh(me)


  def on_doc_changed(me, buffer):
    me.lines = document_lines(me.currentDoc)
    print ('doc_changed lines ' + str(len(me.lines)))
    queue_refresh(me)

  # def on_doc_load(me, doc, file, encoding, line_pos, col_pos):
  #   print ('doc load')

  def on_darea_motion_notify_event(me, widget, event):
    # used for clicking and dragging

    if event.state & Gdk.ModifierType.BUTTON1_MASK:
      me.scroll_from_y_mouse_pos(event.y)
    
  def on_darea_scroll_event(me, widget, event):
    
    pagesize = 12
    topL, botL = visible_lines_top_bottom(me.geditwin)
    if event.direction == Gdk.ScrollDirection.UP and topL > pagesize:
      newI = topL - pagesize
    elif event.direction == Gdk.ScrollDirection.DOWN:
      newI = botL + pagesize
    else:
      return

    me.currentView.scroll_to_iter(me.currentDoc.get_iter_at_line_index(newI,0),0,False,0,0)
    
    queue_refresh(me)
    
  def scroll_from_y_mouse_pos(me,y):

    firstLine = int((len(me.lines) + (me.botL - me.topL)) * y/me.winHeight)
#    if firstLine < 0 : firstLine = 0

    me.currentView.scroll_to_iter(me.currentDoc.get_iter_at_line_index(firstLine,0),0,True,0,.5)

    queue_refresh(me)
    
  def button_press(me, widget, event):
    me.scroll_from_y_mouse_pos(event.y)
  
  def on_scroll_event(me,view,event):
    me.last_scroll_time = time.time()
    queue_refresh(me)
    
  def draw(me, widget, cr):

    if not me.currentDoc or not me.currentView:   # nothing open yet
      return
    
    bg = (0,0,0)
    fg = (1,1,1)
    try:
      style = me.currentDoc.get_style_scheme().get_style('text')
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
    w,h = map(float, (win.get_width(), win.get_height()) )
    cr = widget.get_window().cairo_create()

    me.winHeight = h # remove h alltogether and replace with me.winHeight
    me.winWidth = w

    # Are we drawing everything, or just the scrollbar?
    fontfamily = 'sans-serif'
    cr.select_font_face('monospace', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    
    cr.set_font_size(me.scale)
    me.linePixelHeight = text_extents("L", cr)[1] # make this more global

    me.topL, me.botL = visible_lines_top_bottom(me.geditwin)

    firstLine = 0
   
    cr.push_group()
    
    # bg
    cr.set_source_rgb(*bg)
    cr.move_to(0,0)
    cr.rectangle(0,0,w,h)
    cr.fill()
    cr.move_to(0,0)
    
    if not me.lines:
      return


    # ------------------------ display text silhouette -----------------------

    
    if dark(*fg):
      faded_fg = lighten(.5,*fg)
    else:
      faded_fg = darken(.5,*fg)
    
    cr.set_source_rgb(*fg)

    textViewLines = int(h/me.linePixelHeight)

    firstLine = me.topL - int((textViewLines - (me.botL - me.topL)) * float(me.topL)/float(len(me.lines)))
    if firstLine < 0: firstLine = 0

    lastLine =  firstLine + textViewLines
    if lastLine > len(me.lines): lastLine = len(me.lines)


    sofarH = 0

    for i in range(firstLine, lastLine, 1):
      cr.show_text(me.lines[i].raw)  
      sofarH += me.linePixelHeight
      cr.move_to(0, sofarH)

    cr.set_source(cr.pop_group())  # draw everything but the scrollbar
    cr.rectangle(0,0,w,h)
    cr.fill()
        
    # ------------------------------- scrollbar -------------------------------

    scrollbar(me.linePixelHeight, me.lines, me.topL, me.botL,w,h,cr, firstLine)
    
    
class TextmapWindowHelper:
  def __init__(me, plugin, window):
    me.window = window
    me.plugin = plugin

    panel = me.window.get_side_panel()
    image = Gtk.Image()
    image.set_from_stock(Gtk.STOCK_DND_MULTIPLE, Gtk.IconSize.BUTTON)
    me.textmapview = TextmapView(me.window)
    me.ui_id = panel.add_item(me.textmapview, "TextMap", "textMap", image)
    
    me.panel = panel

  def deactivate(me):
    me.window = None
    me.plugin = None
    me.textmapview = None

  def update_ui(me):
    queue_refresh(me.textmapview)
    
    
class WindowActivatable(GObject.Object, Gedit.WindowActivatable):
  
  window = GObject.property(type=Gedit.Window)

  def __init__(self):
    GObject.Object.__init__(self)
    self._instances = {}

  def do_activate(self):
    self._instances[self.window] = TextmapWindowHelper(self, self.window)

  def do_deactivate(self):
    if self.window in self._instances:
      self._instances[self.window].deactivate()

  def update_ui(self):
    if self.window in self._instances:
      self._instances[self.window].update_ui()
