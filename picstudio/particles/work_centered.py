"""Orbit gather dual to the order-one Esirkepov scatter (Cartesian ZY).

The two endpoint shape differences are the SAME as in kernels.esirkepov_2d.
Consequently q E_orbit dot (x1-x0) equals the native-grid current work, including
cell crossings. This is a discrete work pairing, not a nodal interpolation.
"""
import math
import numpy as np
from numba import njit, prange


@njit(inline='always')
def _value(a, i, j, nz, ny, pz, py):
    if pz: i %= nz
    if py: j %= ny
    if i < 0 or j < 0 or i >= a.shape[0] or j >= a.shape[1]: return 0.
    return a[i,j]


@njit(inline='always')
def _face_weight(a,b,i):
    """Stable normalized Esirkepov face flux: no subtraction of nearly equal shapes."""
    delta=b-a;mid=.5*(a+b)
    if delta==0.:
        if abs(mid-round(mid))<1e-12:
            node=int(round(mid));return .5 if i in (node-1,node) else 0.
        return 1. if i==int(math.floor(mid)) else 0.
    if int(math.floor(a))==int(math.floor(b)):
        return 1. if i==int(math.floor(a)) else 0.
    return max(0.,min(max(a,b),i+1.)-max(min(a,b),float(i)))/abs(delta)


@njit(cache=True, nogil=True, parallel=True)
def orbit_gather(E0,E1,E2,x0,y0,x1,y1,nz,ny,pz,py):
    """Gather native electric fields along logical-coordinate endpoints.

    E0/E1 are flux-weighted in their staggered direction. E2 uses the exact
    transverse Esirkepov moment, including its dSx*dSy/3 term.
    Paths must move at most one cell in each direction (scatter's requirement).
    """
    n=len(x0); out=np.zeros((3,n))
    for p in prange(n):
        ix=int(math.floor(x0[p])); iy=int(math.floor(y0[p]))
        dx=x1[p]-x0[p]; dy=y1[p]-y0[p]
        sx0=np.empty(4);sx1=np.empty(4);sy0=np.empty(4);sy1=np.empty(4)
        for k in range(4):
            sx0[k]=max(0.,1.-abs(x0[p]-(ix-1+k)))
            sx1[k]=max(0.,1.-abs(x1[p]-(ix-1+k)))
            sy0[k]=max(0.,1.-abs(y0[p]-(iy-1+k)))
            sy1[k]=max(0.,1.-abs(y1[p]-(iy-1+k)))
        for l in range(4):
            acc=0.; sh=.5*(sy0[l]+sy1[l])
            for k in range(4):
                acc-=sx1[k]-sx0[k]
                weight=_face_weight(x0[p],x1[p],ix-1+k)
                out[0,p]+=weight*sh*_value(E0,ix-1+k,iy-1+l,nz,ny,pz,py)
        for k in range(4):
            acc=0.; sh=.5*(sx0[k]+sx1[k])
            for l in range(4):
                acc-=sy1[l]-sy0[l]
                weight=_face_weight(y0[p],y1[p],iy-1+l)
                out[1,p]+=weight*sh*_value(E1,ix-1+k,iy-1+l,nz,ny,pz,py)
        for k in range(4):
            for l in range(4):
                dsx=sx1[k]-sx0[k];dsy=sy1[l]-sy0[l]
                sh=sx0[k]*sy0[l]+.5*dsx*sy0[l]+.5*sx0[k]*dsy+dsx*dsy/3.
                out[2,p]+=sh*_value(E2,ix-1+k,iy-1+l,nz,ny,pz,py)
    return out


@njit(cache=True,nogil=True)
def paired_flux(x0,y0,x1,y1,v2_fraction,weights,charge,nz,ny,pz,py):
    """Same Esirkepov fluxes, evaluated with stable overlaps for tiny birth paths.

    Returns physical native arrays, including duplicated periodic node rows.
    No filtering, changed shape function, or charge correction is introduced.
    """
    fz=np.zeros((nz,ny+1));fy=np.zeros((nz+1,ny));q2=np.zeros((nz+1,ny+1))
    for p in range(len(x0)):
        ix=int(math.floor(x0[p]));iy=int(math.floor(y0[p]));q=charge*weights[p]
        dx=x1[p]-x0[p];dy=y1[p]-y0[p]
        for k in range(4):
            i=ix-1+k
            sx0=max(0.,1.-abs(x0[p]-i));sx1=max(0.,1.-abs(x1[p]-i));dsx=sx1-sx0
            fx=_face_weight(x0[p],x1[p],i)
            for l in range(4):
                j=iy-1+l
                sy0=max(0.,1.-abs(y0[p]-j));sy1=max(0.,1.-abs(y1[p]-j));dsy=sy1-sy0
                fyw=_face_weight(y0[p],y1[p],j)
                ii=i%nz if pz else i;jj=j%ny if py else j
                if 0<=ii<nz and 0<=jj<ny+1:fz[ii,jj]+=q*dx*fx*.5*(sy0+sy1)
                if 0<=ii<nz+1 and 0<=jj<ny:fy[ii,jj]+=q*dy*fyw*.5*(sx0+sx1)
                if 0<=ii<nz+1 and 0<=jj<ny+1:
                    W=sx0*sy0+.5*dsx*sy0+.5*sx0*dsy+dsx*dsy/3.
                    q2[ii,jj]+=q*v2_fraction[p]*W
    if pz:fy[-1]=fy[0];q2[-1]=q2[0]
    if py:fz[:,-1]=fz[:,0];q2[:,-1]=q2[:,0]
    return fz,fy,q2


@njit(cache=True, nogil=True, parallel=True)
def first_absorption(x0,y0,x1,y1,cell_obj,nz,ny,pz,py):
    """First painted-cell or outer absorbing-surface intersection on a segment.

    Coordinates are logical/unwrapped. Reflecting boundaries are rejected by
    model validation for the work-centered integrator; periodic seams wrap only
    for material lookup, leaving the current path continuous.
    """
    n=len(x0);fraction=np.ones(n);flags=np.zeros(n,np.int32)
    for p in prange(n):
        dx=x1[p]-x0[p];dy=y1[p]-y0[p];end=1.;flag=0
        if not pz:
            if x1[p]<0. and dx<0.: end=-x0[p]/dx;flag=1
            if x1[p]>=nz and dx>0.: end=(nz-x0[p])/dx;flag=2
        if not py:
            if y1[p]<0. and dy<0.:
                a=-y0[p]/dy
                if a<=end: end=a;flag=3
            if y1[p]>=ny and dy>0.:
                a=(ny-y0[p])/dy
                if a<=end: end=a;flag=4
        i=int(math.floor(x0[p]+(1e-10 if dx>0 else -1e-10 if dx<0 else 0.)))
        j=int(math.floor(y0[p]+(1e-10 if dy>0 else -1e-10 if dy<0 else 0.)))
        at=0.
        for _ in range(8):  # at most one cell/axis, plus corner and seam cases
            ii=i%nz if pz else i; jj=j%ny if py else j
            if 0<=ii<nz and 0<=jj<ny and cell_obj[ii,jj]>=0:
                end=max(0.,at);flag=10+cell_obj[ii,jj];break
            tx=((i+1-x0[p])/dx if dx>0 else (i-x0[p])/dx if dx<0 else 1e30)
            ty=((j+1-y0[p])/dy if dy>0 else (j-y0[p])/dy if dy<0 else 1e30)
            nxt=min(tx,ty)
            if nxt>end or nxt>1.:break
            at=nxt
            if tx<=ty+1e-13: i+=1 if dx>0 else -1
            if ty<=tx+1e-13: j+=1 if dy>0 else -1
        fraction[p]=max(0.,min(1.,end));flags[p]=flag
    return fraction,flags
