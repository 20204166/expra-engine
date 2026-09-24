"""Blacksite Relay game rules for the current Expra checkout."""
from __future__ import annotations
import math
from typing import Any, cast
from expra_engine.core.component import TransformComponent
from expra_engine.core.engine import EngineRunState
from expra_engine.runtime.behaviour import Behaviour, exposed
from expra_engine.runtime.physics_world import PhysicsWorld2D
from expra_engine.runtime.rendering import Color
from expra_engine.runtime.visual_components import PrimitiveComponent, TextComponent

class BlacksiteRelayBehaviour(Behaviour):
    player_speed=exposed(15.0,min=1.0,max=40.0,step=0.5,category='Player')
    enemy_speed=exposed(4.2,min=0.5,max=18.0,step=0.1,category='Enemies')
    shot_range=exposed(18.0,min=2.0,max=35.0,step=0.5,category='Combat')
    shot_cooldown_seconds=exposed(0.28,min=0.05,max=2.0,step=0.01,category='Combat')
    mission_seconds=exposed(120.0,min=20.0,max=600.0,step=5.0,category='Mission')
    reinforcement_interval=exposed(26.0,min=5.0,max=90.0,step=1.0,category='Enemies')
    def __init__(self):
        super().__init__(); self.physics=None; self.health=5; self.shards=0; self.vip=0; self.kills=0; self.elapsed=0.0; self.state='playing'; self.invulnerable=0.0; self.shot_cooldown=0.0; self.beam_timer=0.0; self.last_aim=(1.0,0.0); self.next_reinforcement=0.0; self.reserve_ids=[]; self.reserve_cursor=0; self.message=''; self.message_timer=0.0
    def on_start(self):
        scene=cast(Any,self.scene); self.physics=PhysicsWorld2D(scene, observer=getattr(self.engine, "observer", None)); self.health=5; self.shards=0; self.vip=0; self.kills=0; self.elapsed=0.0; self.state='playing'; self.invulnerable=0.0; self.shot_cooldown=0.0; self.beam_timer=0.0; self.last_aim=(1.0,0.0); self.next_reinforcement=float(self.reinforcement_interval); self.reserve_ids=[e.entity_id for e in scene.get_entities_by_tag('enemy_reserve')]; self.reserve_cursor=0
        for e in scene.get_entities_by_tag('enemy_start'): e.enabled=True
        for e in scene.get_entities_by_tag('enemy_reserve'): e.enabled=False
        for tag in ('shard','vip'):
            for e in scene.get_entities_by_tag(tag): e.enabled=True
        self._set_beam(False); self._set_message('COLLECT 4 SHARDS + RESCUE ENGINEER',3.0); self._refresh_hud(); self._update_aim_indicator()
    def on_stop(self): self.physics=None
    def on_fixed_update(self,dt):
        dt=max(0.0,float(dt)); self.invulnerable=max(0.0,self.invulnerable-dt); self.shot_cooldown=max(0.0,self.shot_cooldown-dt); self.beam_timer=max(0.0,self.beam_timer-dt); self.message_timer=max(0.0,self.message_timer-dt)
        if self.beam_timer<=0: self._set_beam(False)
        if self.state!='playing': self._animate_exit(); self._refresh_hud(); return
        self.elapsed+=dt
        if self.elapsed>=float(self.mission_seconds): self._lose('MISSION CLOCK EXPIRED // R RESTART'); return
        self._move_player(dt); self._move_enemies(dt); self._handle_contacts(); self._spawn_reinforcement(); self._animate_exit(); self._refresh_hud()
    def on_input(self,event,signal=None):
        del signal; action=getattr(getattr(event,'action',None),'value',None); phase=getattr(event,'phase',None)
        if phase!='pressed': return False
        if action=='pause': return self._toggle_pause()
        if action=='restart': return self._restart()
        if action in {'fire','fire_alt'} and self.state=='playing': return self._fire()
        return False
    def _held(self,*actions): return any(self.input.is_held(a) for a in actions)
    def _move_player(self,dt):
        p=self._entity('player'); t=self._transform('player')
        dx=float(self._held('move_right','move_right_alt'))-float(self._held('move_left','move_left_alt')); dy=float(self._held('move_up','move_up_alt'))-float(self._held('move_down','move_down_alt')); length=math.hypot(dx,dy)
        if length==0: return
        dx,dy=dx/length,dy/length; self.last_aim=(dx,dy); old=(t.x,t.y); t.x=max(-38.5,min(38.5,t.x+dx*float(self.player_speed)*dt)); t.y=max(-16.2,min(16.2,t.y+dy*float(self.player_speed)*dt)); self._update_aim_indicator()
        if self.physics:
            for oid in self.physics.overlap(p.entity_id):
                other=cast(Any,self.scene).find_entity(oid)
                if other is not None and other.has_tag('obstacle'): t.x,t.y=old; break
    def _update_aim_indicator(self):
        t=self._transform('aim_indicator'); dx,dy=self.last_aim; t.x=dx*3.0; t.y=dy*3.0; t.rotation=math.degrees(math.atan2(dy,dx))
    def _move_enemies(self,dt):
        pt=self._transform('player'); speed=float(self.enemy_speed)*(1.0+0.05*(self.shards+self.vip))
        for e in cast(Any,self.scene).get_entities_by_tag('enemy'):
            if not e.enabled: continue
            t=e.get_component(TransformComponent)
            if t is None: continue
            dx,dy=pt.x-t.x,pt.y-t.y; dist=math.hypot(dx,dy)
            if dist<0.001: continue
            factor=0.45 if dist<3.2 else 1.0; t.x=max(-38.5,min(38.5,t.x+dx/dist*speed*factor*dt)); t.y=max(-16.2,min(16.2,t.y+dy/dist*speed*factor*dt))
    def _handle_contacts(self):
        if not self.physics: return
        p=self._entity('player'); touching=None
        for oid in self.physics.overlap(p.entity_id,include_triggers=True):
            o=cast(Any,self.scene).find_entity(oid)
            if o is None or not o.enabled: continue
            if o.has_tag('shard'): o.enabled=False; self.shards+=1; self._set_message(f'ACCESS SHARD {self.shards}/4 SECURED',1.5); self._check_ready()
            elif o.has_tag('vip'): o.enabled=False; self.vip=1; self._set_message('ENGINEER RESCUED',1.8); self._check_ready()
            elif o.has_tag('extraction'):
                if self._ready(): self._win()
                elif self.message_timer<=0: self._set_message('EXIT LOCKED // COMPLETE OBJECTIVES',1.2)
            elif o.has_tag('enemy') and touching is None: touching=o
        if touching is not None and self.invulnerable<=0: self._damage(touching)
    def _damage(self,enemy):
        self.health-=1; self.invulnerable=0.9; p=self._transform('player'); et=enemy.get_component(TransformComponent)
        if et is not None:
            dx,dy=p.x-et.x,p.y-et.y; length=math.hypot(dx,dy) or 1.0; p.x=max(-38.5,min(38.5,p.x+dx/length*2.8)); p.y=max(-16.2,min(16.2,p.y+dy/length*2.8))
        if self.health<=0: self._lose('OPERATIVE DOWN // R RESTART')
        else: self._set_message(f'SUIT HIT // HP {self.health}/5',1.1)
    def _fire(self):
        if self.shot_cooldown>0 or not self.physics: return False
        self.shot_cooldown=float(self.shot_cooldown_seconds); p=self._transform('player'); aim=self.last_aim; hit=self.physics.raycast((p.x,p.y),aim,float(self.shot_range),mask=(2|16),include_triggers=False); x2=p.x+aim[0]*float(self.shot_range); y2=p.y+aim[1]*float(self.shot_range)
        if hit.hit:
            x2,y2=hit.point; target=cast(Any,self.scene).find_entity(hit.entity_id) if hit.entity_id else None
            if target is not None and target.has_tag('enemy') and target.enabled: target.enabled=False; self.kills+=1; self._set_message(f'DRONE DISABLED // {self.kills}',0.7)
        self._show_beam(p.x,p.y,x2,y2); return True
    def _show_beam(self,x1,y1,x2,y2):
        b=self._entity('shot_beam'); t=b.get_component(TransformComponent); v=b.get_component(PrimitiveComponent)
        if t is None or v is None: return
        dx,dy=x2-x1,y2-y1; t.x,t.y=(x1+x2)/2,(y1+y2)/2; t.rotation=math.degrees(math.atan2(dy,dx)); v.width=max(0.1,math.hypot(dx,dy)); v.visible=True; self.beam_timer=0.08
    def _set_beam(self,visible):
        v=self._entity('shot_beam').get_component(PrimitiveComponent)
        if v is not None: v.visible=bool(visible)
    def _spawn_reinforcement(self):
        if self.reserve_cursor>=len(self.reserve_ids) or self.elapsed<self.next_reinforcement: return
        e=cast(Any,self.scene).find_entity(self.reserve_ids[self.reserve_cursor]); self.reserve_cursor+=1; self.next_reinforcement+=float(self.reinforcement_interval)
        if e is not None: e.enabled=True; self._set_message('SECURITY REINFORCEMENT ONLINE',1.4)
    def _ready(self): return self.shards>=4 and self.vip>=1
    def _check_ready(self):
        if self._ready(): self._set_message('EXIT UNLOCKED // REACH NORTH-EAST GATE',2.8)
    def _animate_exit(self):
        v=self._entity('extraction').get_component(PrimitiveComponent); b=self._entity('extraction_beacon').get_component(PrimitiveComponent)
        if v is None or b is None: return
        pulse=0.58+0.22*math.sin(self.elapsed*5.0)
        if self._ready() or self.state=='won': v.fill=Color(0.04,0.34,0.18,0.95); v.outline=Color(0.18,1.0,0.52,1); b.fill=Color(0.2,1.0,0.58,pulse)
        else: v.fill=Color(0.24,0.055,0.07,0.85); v.outline=Color(0.92,0.22,0.28,1); b.fill=Color(1.0,0.24,0.30,pulse)
    def _win(self):
        if self.state!='playing': return
        self.state='won'; self._set_message(f'MISSION COMPLETE // {self.kills} DRONES DISABLED // R RESTART',999)
        for e in cast(Any,self.scene).get_entities_by_tag('enemy'): e.enabled=False
    def _lose(self,msg): self.state='lost'; self._set_message(msg,999)
    def _refresh_hud(self):
        remain=max(0,int(math.ceil(float(self.mission_seconds)-self.elapsed))); self._set_text('hud_health',f'HP {max(0,self.health)}/5'); self._set_text('hud_objective',f'SHARDS {self.shards}/4  //  VIP {self.vip}/1'); ready='READY' if self.shot_cooldown<=0 else f'{self.shot_cooldown:.1f}s'; self._set_text('hud_time',f'TIME {remain}  //  {ready}')
        if self.message_timer>0: self._set_text('hud_status',self.message)
        elif self.state=='playing': self._set_text('hud_status','EXIT UNLOCKED' if self._ready() else 'COLLECT 4 SHARDS + RESCUE ENGINEER')
    def _set_message(self,msg,duration): self.message=str(msg); self.message_timer=float(duration); self._set_text('hud_status',self.message)
    def _set_text(self,tag,value):
        c=self._entity(tag).get_component(TextComponent)
        if c is not None: c.text=value
    def _toggle_pause(self):
        e=cast(Any,self.engine)
        if e is None: return False
        if e.run_state is EngineRunState.PLAY: return e.pause()
        if e.run_state is EngineRunState.PAUSED: return e.play()
        return False
    def _restart(self):
        e=cast(Any,self.engine)
        if e is None or e.run_state not in (EngineRunState.PLAY,EngineRunState.PAUSED): return False
        e.stop(); return e.play()
    def _entity(self,tag):
        m=cast(Any,self.scene).get_entities_by_tag(tag)
        if not m: raise LookupError(f'missing tagged entity: {tag}')
        return m[0]
    def _transform(self,tag):
        t=self._entity(tag).get_component(TransformComponent)
        if t is None: raise LookupError(f'no transform: {tag}')
        return t
