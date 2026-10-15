"""Draw the provenance lanes and four reduction dependencies directly in Python.
Requires Python 3.9+ and Matplotlib. These are explanatory diagrams, not measurements.
"""
import argparse
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Polygon, Circle, FancyArrowPatch

plt.rcParams.update({'font.family':'STIXGeneral', 'mathtext.fontset':'stix',
                     'font.size':9, 'pdf.fonttype':42, 'ps.fonttype':42,
                     'text.usetex':False, 'axes.unicode_minus':False})
CM = 1 / 2.54

class Drawing:
    def __init__(self, bounds):
        x0,y0,x1,y1 = bounds
        self.fig = plt.figure(figsize=((x1-x0)*CM,(y1-y0)*CM))
        self.ax = self.fig.add_axes([0,0,1,1], xlim=(x0,x1), ylim=(y0,y1))
        self.ax.set_aspect('equal'); self.ax.axis('off')
        self.nodes = {}
        self.labels = []

    def text(self,x,y,label,size=9,ha='center',va='center'):
        artist=self.ax.text(x,y,label,fontsize=size,ha=ha,va=va,
                            linespacing=1.15,clip_on=False,zorder=4)
        self.labels.append([artist,None])
        return artist

    def box(self,name,x,y,w,h,label,dashed=False,shape='rect',size=9):
        style = {'edgecolor':'black','facecolor':'white','linewidth':.55,
                 'linestyle':(0,(4,3)) if dashed else 'solid', 'zorder':2}
        if shape == 'diamond':
            obj = Polygon([(x-w/2,y),(x,y+h/2),(x+w/2,y),(x,y-h/2)],**style)
        elif shape == 'circle': obj = Circle((x,y),w/2,**style)
        else: obj = Rectangle((x-w/2,y-h/2),w,h,**style)
        self.ax.add_patch(obj); self.text(x,y,label,size)
        self.labels[-1][1]=(x-w/2,y-h/2,x+w/2,y+h/2)
        self.nodes[name] = (x,y,w,h,shape)

    def point(self,name,side):
        x,y,w,h,_ = self.nodes[name]
        return {'n':(x,y+h/2),'s':(x,y-h/2),'e':(x+w/2,y),
                'w':(x-w/2,y),'nw':(x-w/2,y+h/2),
                'ne':(x+w/2,y+h/2),'c':(x,y)}[side]

    def line(self,points,dashed=False):
        xs,ys=zip(*points)
        self.ax.plot(xs,ys,color='black',linewidth=.55,
                     linestyle=(0,(4,3)) if dashed else 'solid',zorder=1)

    def arrow(self,p,q,dashed=False,via=()):
        points=[p,*via,q]
        if via:self.line(points[:-1],dashed)
        self.ax.add_patch(FancyArrowPatch(points[-2],points[-1],
                         arrowstyle='-|>',mutation_scale=7.5,linewidth=.55,
                         color='black',shrinkA=0,shrinkB=0,
                         linestyle=(0,(4,3)) if dashed else 'solid',zorder=1))

    def edge(self,a,b,sa='s',sb='n',**kwargs):
        self.arrow(self.point(a,sa),self.point(b,sb),**kwargs)

    def frame(self,x,y,w,h):
        self.ax.add_patch(Rectangle((x,y),w,h,fill=False,edgecolor='black',
                                   linewidth=.55,linestyle=(0,(4,3)),zorder=0))

    def save(self,out,name):
        # Fixed physical canvas: do not enlarge or rasterize the scientific figure.
        self.fig.canvas.draw()
        renderer=self.fig.canvas.get_renderer()
        x0,x1=self.ax.get_xlim();y0,y1=self.ax.get_ylim()
        for artist,node in self.labels:
            b=artist.get_window_extent(renderer).transformed(self.ax.transData.inverted())
            if b.x0<x0-.02 or b.x1>x1+.02 or b.y0<y0-.02 or b.y1>y1+.02:
                raise ValueError(name+': clipped label '+repr(artist.get_text()))
            if node and (b.x0<node[0]-.02 or b.x1>node[2]+.02 or b.y0<node[1]-.02 or b.y1>node[3]+.02):
                raise ValueError(name+': label exceeds node '+repr(artist.get_text()))
        self.fig.savefig(out/(name+'.pdf'),format='pdf',
                         metadata={'Creator':'Python Matplotlib','Producer':None,
                                   'CreationDate':None,'ModDate':None})
        plt.close(self.fig)





def draw(out):
    d=Drawing((0,0,17.65,5.8))
    for x,stage in ((3.45,'Compile'),(7.7,'Package'),(11.95,'Release')):
        d.text(x,5.3,stage,size=9)
    d.text(.95,4.3,'Signed\nrecord',size=9)
    d.text(.95,1.35,'Marked\nartifact',size=9)
    for i,x in enumerate((3.45,7.7,11.95)):
        label=rf'$r_{i}$'+'\n'+(r'binder $b_0$' if i==0 else rf'parent $d_{i-1}$')
        d.box('r'+str(i),x,4.3,2.35,.88,label,size=9)
        d.box('p'+str(i),x,1.35,2.35,.88,rf'$P_{i}$'+'\n'+rf'tip $d_{i}$',size=9)
    for i in range(2):
        d.edge('r'+str(i),'r'+str(i+1),sa='e',sb='w')
        d.text(5.575+4.25*i,4.57,rf'digest $d_{i}$',size=8.5)
        d.edge('p'+str(i),'p'+str(i+1),sa='e',sb='w')
        d.text(5.575+4.25*i,.86,'approved\nstep',size=8.5)
    # Explicit sides preserve upward host binding and downward marking flow.
    d.edge('p0','r0',sa='n',sb='s',dashed=True)
    d.text(2.75,2.85,'host\nbinder',size=8.5)
    d.edge('r1','p1',sa='s',sb='n',dashed=True)
    d.text(8.4,2.85,'derived\nkey',size=8.5)
    d.edge('r2','p2',sa='s',sb='n',dashed=True)
    d.text(12.65,2.85,'exact\npayload',size=8.5)
    d.box('verifier',15.65,2.825,3.15,1.3,'accept iff\nchain, binder,\nand tip agree',size=9)
    d.edge('r2','verifier',sa='e',sb='nw',via=((13.5,4.3),(13.5,3.475)))
    # South-west corner is supplied explicitly to avoid an undeclared primitive.
    d.arrow(d.point('p2','e'),(14.075,2.175),via=((13.5,1.35),(13.5,2.175)))
    d.save(out,'architecture')

    d=Drawing((0,0,17.2,5.65))
    d.box('switch',8.6,5,16.6,.8,
          'Common hybrid: replace every context-derived key by an independent random key;\n'+r'pay $\varepsilon_{\rm prf}(Q_{\rm att})$ once.',size=9)
    d.box('issued',4.3,3.75,7.7,.9,'Issued-object branch: challenger supplied\nthe target chain or coalition group.',size=9)
    d.box('candidate',12.9,3.75,7.7,.9,'Candidate-chain branch: authenticate all submitted\nrecords; an unissued record pays the chain loss.',size=9)
    cards=[('removal',2.15,'Removal\nAdmitted derivative.\nBinder instability\nor lost tip.\n'+r'$Q_{\rm iss}(\delta_{\rm stab}+\varepsilon_{\rm rm})$'),
           ('coalition',6.45,'Coalition\nDeclared copy group.\nBinder instability or\nfailed trace.\n'+r'$G(\delta_{\rm stab}+\varepsilon_{\rm col}(c))$'),
           ('transfer',10.75,'Transfer\nAuthenticated candidate.\nUnrelated host accepts\nthe exact tip.\nChain + smaller marginal'),
           ('origin',15.05,'Origin\nAuthenticated candidate.\nOutput leaves the\npublic closure.\n'+r'Chain $+Q_{\rm iss}\varepsilon_{\rm uf}$')]
    for name,x,label in cards:d.box(name,x,1.55,4.0,2.25,label,size=9)
    for parent in ('issued','candidate'):
        x=d.nodes[parent][0];d.arrow((x,4.6),d.point(parent,'n'))
    for parent,children in (('issued',('removal','coalition')),('candidate',('transfer','origin'))):
        for child in children:
            x=d.nodes[child][0];d.arrow((x,3.3),d.point(child,'n'))
    d.save(out,'reductions')

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=Path(__file__).resolve().parent)
    out=parser.parse_args().output
    out.mkdir(parents=True,exist_ok=True)
    draw(out)
