from tkinter import *
from geometry import Bounds, Point2D, Vector2D
import sys
import time
import urllib.request as request
import subprocess
import os
import ctypes
from socketIO_client_nexus import SocketIO, BaseNamespace
import threading
import queue

'''
queues for sharing information across threads for multiplayer
q is queue for sending PacMan position to network
p is for recieving other player's positions
s is for getting our socket id (used once)
'''
q = queue.Queue()
p = queue.Queue()
s = queue.Queue()

# called whenever server emits 'frame' event,
# puts other player's positions into queue
def recieveFrame(data):
    p.queue.clear()
    p.put(data)

# listens for 'frame' events and calls recieveFrame on each frame
def listen():
    with SocketIO('pacman-at-reed.herokuapp.com', 80, BaseNamespace) as socket:
        socket.on('frame', recieveFrame)
        socket.wait()

# emits checkin events every 0.1 seconds, will show on other client's screen
def broadcast():
    with SocketIO('pacman-at-reed.herokuapp.com', 80, BaseNamespace) as socket:
        s.put(socket._engineIO_session.id)
        while True:
            pass
            if q.empty() != True:
                e = q.get()
                if e == False:
                    socket.disconnect()
                socket.emit('checkin', {
                    'positionX': e.position.x,
                    'positionY': e.position.y
                })
            time.sleep(0.1)

# creates threads for listening and broadcasting
tasks = [listen, broadcast]
for task in tasks:
    t = threading.Thread(target=task)
    t.start()

# thank you stackoverflow
# https://stackoverflow.com/questions/1969240/mapping-a-range-of-values-to-another
# originally I used numpy
def translate(value, leftMin, leftMax, rightMin, rightMax):
    # Figure out how 'wide' each range is
    leftSpan = leftMax - leftMin
    rightSpan = rightMax - rightMin

    # Convert the left range into a 0-1 range (float)
    valueScaled = float(value - leftMin) / float(leftSpan)

    # Convert the 0-1 range into a value in the right range.
    return rightMin + (valueScaled * rightSpan)

socketID = ''

class Agent:

    INTENSITIES = [4,5,6,7,8,7,6,5,4,3,2,1,0,1,2,3]

    def __init__(self,position,world):
        self.position = position
        self.world    = world
        self.world.add(self)
        self.ticks    = 0

    def color(self):
        a = self.ticks % len(self.INTENSITIES)
        return "#0000"+str(self.INTENSITIES[a])+"0"

    def shape(self):
        p1 = self.position + Vector2D( 0.125, 0.125)
        p2 = self.position + Vector2D(-0.125, 0.125)
        p3 = self.position + Vector2D(-0.125,-0.125)
        p4 = self.position + Vector2D( 0.125,-0.125)
        return [p1,p2,p3,p4]

    def update(self):
        self.ticks += 1

    def leave(self):
        self.world.remove(self)

class Game(Frame):

    # Game(name,w,h,ww,wh)
    #
    # Creates a world with a coordinate system of width w and height
    # h, with x coordinates ranging between -w/2 and w/2, and with y
    # coordinates ranging between -h/2 and h/2.
    #
    # Creates a corresponding graphics window, for rendering
    # the world, with pixel width ww and pixel height wh.
    #
    # The window will be named by the string given in name.
    #
    # The topology string is used by the 'trim' method to (maybe) keep
    # bodies within the frame of the world. (For example, 'wrapped'
    # yields "SPACEWAR" topology, i.e. a torus.)
    #
    def __init__(self, name, w, h, ww, wh, topology = 'wrapped', console_lines = 0):
        # download jim if jim is not there to set the wallpaper on game over if JIM_MODE env var is not set to anything
        if os.path.isfile('fix-james-d.jpg') == False:
            request.urlretrieve('https://www.reed.edu/dean_of_faculty/faculty_profiles/profiles/photos/fix-james-d.jpg', 'fix-james-d.jpg')
        self.wallpaperSet = False

        self.paused = False
        self.gameOver = False

        # Register the world coordinate and graphics parameters.
        self.WIDTH = w
        self.HEIGHT = h
        self.WINDOW_WIDTH = ww
        self.WINDOW_HEIGHT = wh
        self.bounds = Bounds(-w/2,-h/2,w/2,h/2)
        self.topology = topology

        # Populate the world with creatures
        self.agents = []
        self.display = 'test'
        self.GAME_OVER = False

        # Populate the background with the walls for pacman
        self.prevWalls = None
        self.walls = []

        # Initialize the graphics window.
        self.root = Tk()
        self.root.title(name)
        # grab window focus after game starts
        self.root.after(500, lambda: self.root.grab_set_global())
        Frame.__init__(self, self.root)
        self.canvas = Canvas(self.root, width=self.WINDOW_WIDTH, height=self.WINDOW_HEIGHT)

        # Handle mouse pointer motion and keypress events.
        self.mouse_position = Point2D(0.0,0.0)
        self.mouse_down     = False
        self.bind_all('<Motion>',self.handle_mouse_motion)
        self.canvas.bind('<Button-1>',self.handle_mouse_press)
        self.canvas.bind('<ButtonRelease-1>',self.handle_mouse_release)
        self.bind_all('<Key>',self.handle_keypress)

        self.canvas.pack()
        if console_lines > 0:
            self.text = Text(self.root,height=console_lines,bg="#000000",fg="#A0F090",width=115)
            self.text.pack()
        else:
            self.text = None
        self.pack()

        # keep track of multiplayer
        self.otherPlayers = []
        self.socketID = []

    def trim(self,agent):
        if self.topology == 'wrapped':
            agent.position = self.bounds.wrap(agent.position)
        elif self.topology == 'bound':
            agent.position = self.bounds.clip(agent.position)
        elif self.topology == 'open':
            pass

    def add(self, agent):
        self.agents.append(agent)

    def remove(self, agent):
        self.agents.remove(agent)

    def update(self):
        # broadcast thread will put socket id in s queue once it connects
        if s.empty():
            pass
        else:
            self.socketID = s.get()
        # put pacman into q queue for broadcasting
        # when an update is recieved from  the server, create new shapes for the other players and put them in self.otherPlayers
        if self.PacMan and self.gameOver != True:
            q.put(self.PacMan)
            otherPlayers = p.get()
            self.otherPlayers = []
            for player in otherPlayers:
                if player != self.socketID:
                    # h = translate(x, 0, 30, -15, 15)
                    # v = translate(y, 0, 45, -22, 22) - .45
                    h = otherPlayers[player]['x']
                    v = otherPlayers[player]['y']
                    # print(h, v)
                    p1 = Point2D(.5 + h,.5 + v)
                    p2 = Point2D(-.5 + h, .5 + v)
                    p3 = Point2D(-.5 + h, -.5 + v)
                    p4 = Point2D(.5 + h, -.5 + v)

                    self.otherPlayers.append([p1, p2, p3, p4])

        # if the maze hasn't been drawn yet, draw the MazeBoundAgent
        # will re-draw the maze if the maze updates
        if self.prevWalls != self.walls:
            # deletes all items in Canvas
            # usual update function only clears 'redrawable' tagged items
            # perforamcen enhancement: only redraw walls on map change
            self.canvas.delete()
            self.drawBackground()
            self.prevWalls = self.walls
        if self.gameOver == True:
            self.paused = True
            self.canvas.create_text(200, 200, font='inconsolata 50', fill='#FFF', text='game over\n' + self.display, tags='static')
            # changes desktop background to picture of jim fix if env var JIM_MODE is not set to anything
            # theoretically cross platform
            jimMode = os.environ.get('JIM_MODE')
            if self.wallpaperSet == False and jimMode == None:
                # load game over prize
                SCRIPT = """/usr/bin/osascript<<END
                tell application "Finder"
                set desktop picture to POSIX file "%s"
                end tell"""

                filename = os.getcwd() + '/fix-james-d.jpg'
                print(filename)
                try:
                    subprocess.Popen(SCRIPT%filename, shell=True)
                    self.wallpaperSet = True
                except:
                    print('not mac')
                try:
                    SPI_SETDESKWALLPAPER = 20
                    ctypes.windll.user32.SystemParametersInfoA(SPI_SETDESKWALLPAPER, 0, "fix-james-d.jpg.jpg" , 0)
                    self.wallpaperSet = True
                except:
                    print('not windows')
        if self.paused == False:
            for agent in self.agents:
                agent.update()
            self.clear()
            for agent in self.agents:
                self.draw_shape(agent.shape(),agent.color())
            # displays score and lives
            self.canvas.create_text(60, 25, font='inconsolata 20', fill='#FFF', text=self.display, tags='redrawable')
            # draw other players
            for shape in self.otherPlayers:
                self.draw_shape(shape, 'purple')
        Frame.update(self)

    # if tag 'static' is used, it will not be redrawn
    def draw_shape(self, shape, color, tag='redrawable'):
        wh,ww = self.WINDOW_HEIGHT,self.WINDOW_WIDTH
        h = self.bounds.height()
        x = self.bounds.xmin
        y = self.bounds.ymin
        points = [ ((p.x - x)*wh/h, wh - (p.y - y)* wh/h) for p in shape ]
        first_point = points[0]
        points.append(first_point)
        self.canvas.create_polygon(points, fill=color, tags=tag)

    # draws maze outline
    def drawBackground(self):
        # black background
        self.canvas.create_rectangle(0, 0, self.WINDOW_WIDTH, self.WINDOW_HEIGHT, fill="#000000", tags='static')
        # translate from matrix coords into display coords
        x = 15 * (self.WINDOW_WIDTH / self.WIDTH)
        y = 22 * (self.WINDOW_HEIGHT / self.HEIGHT)
        p1 = Point2D(.5,.5)
        p2 = Point2D(-.5, .5)
        p3 = Point2D(-.5, -.5)
        p4 = Point2D(.5, -.5)

        walls = self.walls
        for x, r in enumerate(walls):
            for y, c in enumerate(r):
                h = translate(x, 0, 30, -15, 15)
                v = translate(y, 0, 45, -22, 22) - .45
                if c > 0:
                    p1 = Point2D(.5 + h,.5 + v)
                    p2 = Point2D(-.5 + h, .5 + v)
                    p3 = Point2D(-.5 + h, -.5 + v)
                    p4 = Point2D(.5 + h, -.5 + v)

                    self.draw_shape([p1,p2,p3,p4], 'blue', 'static')

    def clear(self):
        self.canvas.delete('redrawable')

    def window_to_world(self,x,y):
        return self.bounds.point_at(x/self.WINDOW_WIDTH, 1.0-y/self.WINDOW_HEIGHT)

    def handle_mouse_motion(self,event):
        self.mouse_position = self.window_to_world(event.x,event.y)
        #print("MOUSE MOVED",self.mouse_position,self.mouse_down)

    def handle_mouse_press(self,event):
        self.mouse_down = True
        self.handle_mouse_motion(event)
        #print("MOUSE CLICKED",self.mouse_down)

    def handle_mouse_release(self,event):
        self.mouse_down = False
        self.handle_mouse_motion(event)
        #print("MOUSE RELEASED",self.mouse_down)

    def handle_keypress(self,event):
        if event.char == 'q':
            self.GAME_OVER = True
