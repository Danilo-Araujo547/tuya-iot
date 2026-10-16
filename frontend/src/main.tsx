import React, {useCallback, useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Activity, ArrowUpRight, Check, ChevronDown, Cloud, History, ImagePlus, LayoutDashboard, LogOut, Menu, Moon, Power, Radio, RefreshCw, ShieldCheck, Sun, Thermometer, Upload, X, Zap} from 'lucide-react';
import {ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid} from 'recharts';
import {scenes, useBackground} from './backgrounds';
import './style.css';
import './temperature-range.css';
import './navigation.css';

type Reading = {property:string; value:number|boolean; unit:string; observed:number; source:string; stale:boolean; observation_time_known?:boolean};
type Device = {id:string; name:string; capabilities:string[]; controllable:boolean; kind:string; connectivity:string; states:Reading[]; last_command?:Command|null; virtual?:boolean; cloud_snapshot_without_timestamp?:boolean};
type Command = {id:string; status:string; power:boolean; created:number};
type Point = {time:number; value:number|null; min?:number|null; max?:number|null};
type ChartPoint = {time:number; temperature:number|null; humidity:number|null};
type Diagnostics = {tuya_connected:boolean; pending:number; dead:number; commands_unknown:number; oldest_pending:number|null; http_calls_window:number; health:Record<string, Record<string, unknown>>};
let csrf = '';
const time = (epoch:number) => new Date(epoch*1000).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
const clock = (epoch:number) => new Date(epoch*1000).toLocaleTimeString('pt-BR',{timeZone:'America/Sao_Paulo',hour:'2-digit',minute:'2-digit'});
const number = (value:number|undefined) => value === undefined ? '—' : value.toLocaleString('pt-BR',{maximumFractionDigits:1});
const clamp = (value:number, min:number, max:number) => Math.min(max, Math.max(min, value));

async function api<T>(path:string, init:RequestInit={}):Promise<T> {
  const response = await fetch('/api/v1'+path, {...init, credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf,...init.headers}});
  if (response.status === 401) window.dispatchEvent(new Event('session-expired'));
  if (!response.ok) {const data = await response.json().catch(()=>({detail:'Falha de comunicação'})); throw new Error(typeof data.detail==='string'?data.detail:'Solicitação inválida');}
  return response.json();
}

function Dial({temperature}:{temperature:number|undefined}) {
  const active = temperature === undefined ? -1 : Math.round(clamp((temperature+20)/80,0,1)*64);
  return <div className="dial-wrapper" aria-label={'Temperatura atual: '+number(temperature)+' graus Celsius'}>
    <svg viewBox="0 0 260 260" aria-hidden="true">
      <defs><linearGradient id="dial-glow"><stop stopColor="#80cfef"/><stop offset=".5" stopColor="#b3e5de"/><stop offset="1" stopColor="#f4bb75"/></linearGradient></defs>
      {Array.from({length:65},(_,i)=>{
        const angle=(120+i*300/64)*Math.PI/180, major=i%5===0;
        const outer=121, inner=major?108:113;
        return <line key={i} x1={130+Math.cos(angle)*inner} y1={130+Math.sin(angle)*inner} x2={130+Math.cos(angle)*outer} y2={130+Math.sin(angle)*outer}
          stroke={i<=active?'url(#dial-glow)':'rgba(255,255,255,.22)'} strokeWidth={major?2.7:1.8} strokeLinecap="round"/>;
      })}
      <circle cx="130" cy="130" r="98" fill="none" stroke="rgba(255,255,255,.08)"/>
      <text x="64" y="257" textAnchor="middle" className="dial-limit">−20°</text>
      <text x="196" y="257" textAnchor="middle" className="dial-limit">60°</text>
    </svg>
    <div className="dial-core"><Thermometer size={22}/><div className="dial-number">{number(temperature)}<sup>°C</sup></div><span>Temperatura atual</span></div>
  </div>;
}

type Weather = {temperature:number;observed:number;stale:boolean;is_day:boolean;weather_code:number|null;source:string};

function GlassSelect({label,value,options,onChange}:{label:string;value:string;options:{value:string;label:string}[];onChange:(value:string)=>void}) {
  const [open,setOpen]=useState(false), root=useRef<HTMLDivElement>(null), trigger=useRef<HTMLButtonElement>(null);
  const id=React.useId();
  useEffect(()=>{
    if(!open)return;
    const outside=(e:PointerEvent)=>{if(!root.current?.contains(e.target as Node))setOpen(false)};
    document.addEventListener('pointerdown',outside);
    root.current?.querySelector<HTMLButtonElement>('[aria-selected="true"]')?.focus();
    return()=>document.removeEventListener('pointerdown',outside);
  },[open]);
  return <div className="glass-select" ref={root} onBlur={e=>{if(!e.currentTarget.contains(e.relatedTarget as Node))setOpen(false)}} onKeyDown={e=>{
    if(e.key==='Escape'){e.preventDefault();setOpen(false);trigger.current?.focus()}
    if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){
      e.preventDefault();if(!open){setOpen(true);return}
      const items=Array.from(root.current?.querySelectorAll<HTMLButtonElement>('[role="option"]')||[]);
      const current=items.indexOf(document.activeElement as HTMLButtonElement);
      const next=e.key==='Home'?0:e.key==='End'?items.length-1:(current+(e.key==='ArrowDown'?1:-1)+items.length)%items.length;
      items[next]?.focus();
    }
  }}><button ref={trigger} type="button" className="glass-select-trigger" aria-label={label} aria-haspopup="listbox" aria-expanded={open} aria-controls={id} onClick={()=>setOpen(!open)}><span>{options.find(o=>o.value===value)?.label||'Selecione um sensor'}</span><ChevronDown size={12}/></button>
    {open&&<div id={id} role="listbox" aria-label={label} className="glass-select-menu">{options.map(option=><button type="button" role="option" aria-selected={option.value===value} key={option.value} onClick={()=>{onChange(option.value);setOpen(false);trigger.current?.focus()}}><span>{option.label}</span>{option.value===value&&<Check size={13}/>}</button>)}</div>}
  </div>;
}

function OutdoorCard(){
  const [weather,setWeather]=useState<Weather|null>(null),[error,setError]=useState(false);
  useEffect(()=>{
    let active=true;
    const load=()=>api<Weather>('/weather/current').then(data=>{if(active){setWeather(data);setError(false)}}).catch(()=>{if(active)setError(true)});
    void load();const timer=setInterval(()=>void load(),600000);return()=>{active=false;clearInterval(timer)};
  },[]);
  const outdated=error||weather?.stale||!!weather&&Date.now()/1000-weather.observed>7200;
  const available=weather&&Date.now()/1000-weather.observed<=7200;
  const Icon=weather?.weather_code!==null&&weather?.weather_code!==undefined&&weather.weather_code>2?Cloud:weather?.is_day?Sun:Moon;
  return <section className="glass-well outdoor-card" aria-label="Temperatura externa">
    <div className="outdoor-heading"><span className="outdoor-icon"><Icon size={21}/></span><h2>Temperatura externa</h2></div>
    <div className="outdoor-reading" aria-live="polite"><strong>{number(available?weather.temperature:undefined)}<small>°C</small></strong><span>{!weather?(error?'Indisponível':'Consultando…'):outdated?'Atualização pendente':'Ao ar livre'}</span></div>
    <div className="outdoor-footer"><span>Estimativa meteorológica{available?' · '+clock(weather.observed):''}</span><a href="https://open-meteo.com/" target="_blank" rel="noreferrer">Open-Meteo</a></div>
  </section>;
}

function TemperatureRangeCard({deviceId,updatedAt}:{deviceId:string|undefined;updatedAt:number|undefined}) {
  const [hours,setHours]=useState(24), [range,setRange]=useState<{min?:number;max?:number}>({});
  const [loading,setLoading]=useState(false), [error,setError]=useState('');
  useEffect(()=>{
    let active=true;
    const controller=new AbortController();
    async function load(){
      if(!deviceId){setRange({});return}
      setLoading(true);setError('');setRange({});
      const end=new Date(),start=new Date(end.getTime()-hours*3600000);
      const query=new URLSearchParams({property:'temperature',start:start.toISOString(),end:end.toISOString(),aggregation:'hour'});
      try{
        const data=await api<{points:Point[]}>('/devices/'+encodeURIComponent(deviceId)+'/history?'+query,{signal:controller.signal});
        const minima=data.points.flatMap(p=>typeof p.min==='number'&&Number.isFinite(p.min)?[p.min]:[]);
        const maxima=data.points.flatMap(p=>typeof p.max==='number'&&Number.isFinite(p.max)?[p.max]:[]);
        if(active)setRange({min:minima.length?Math.min(...minima):undefined,max:maxima.length?Math.max(...maxima):undefined});
      }catch(e){if(active)setError((e as Error).message)}
      finally{if(active)setLoading(false)}
    }
    void load();const timer=setInterval(()=>void load(),60000);
    return()=>{active=false;controller.abort();clearInterval(timer)};
  },[deviceId,hours,updatedAt]);
  return <section className="glass-well temperature-range" aria-label="Extremos de temperatura">
    <div className="range-heading"><h2><Thermometer size={16}/>Temperatura</h2><GlassSelect label="Período da mínima e máxima" value={String(hours)} onChange={value=>setHours(Number(value))} options={[{value:'1',label:'1h'},{value:'6',label:'6h'},{value:'24',label:'24h'},{value:'168',label:'7 dias'},{value:'720',label:'30 dias'}]}/></div>
    <div className="range-values" aria-live="polite" aria-busy={loading}><div><span>Mínima</span><strong>{number(range.min)}<small>°C</small></strong></div><div><span>Máxima</span><strong>{number(range.max)}<small>°C</small></strong></div></div>
    <p className="range-note" role={error?'alert':'status'}>{loading?'Carregando…':error?'Falha ao consultar histórico':range.min===undefined?'Sem medições no período':'Registradas no período'}</p>
  </section>;
}

function BackgroundDialog({open,onClose,background}:{open:boolean;onClose:()=>void;background:ReturnType<typeof useBackground>}) {
  const dialog=useRef<HTMLDialogElement>(null), input=useRef<HTMLInputElement>(null);
  const [error,setError]=useState(''), [loading,setLoading]=useState(false);
  useEffect(()=>{if(open){dialog.current?.showModal();setError('')}else dialog.current?.close()},[open]);
  return <dialog ref={dialog} onCancel={onClose} onClose={onClose} onClick={e=>{if(e.target===e.currentTarget)onClose()}} className="background-dialog" aria-labelledby="background-title">
    <div className="dialog-heading"><div><p className="eyebrow">DO SEU JEITO</p><h2 id="background-title">O cenário do seu espaço.</h2></div><button className="icon-button" aria-label="Fechar personalização" onClick={onClose}><X size={19}/></button></div>
    <p className="dialog-copy">Escolha uma das imagens da referência ou use uma foto sua.</p>
    <div className="scene-grid">{scenes.map(scene=><button key={scene.id} disabled={background.saving} className={'scene-option '+(background.id===scene.id?'chosen':'')} aria-pressed={background.id===scene.id} onClick={()=>void background.choose(scene.id)}>
      <img src={scene.url.replace('w=2000','w=480')} alt="" loading="lazy"/><span>{scene.name}{background.id===scene.id&&<Check size={15}/>}</span></button>)}</div>
    <input ref={input} type="file" tabIndex={-1} accept="image/jpeg,image/png,image/webp" aria-label="Imagem de fundo personalizada" className="file-input" onChange={async e=>{
      const file=e.target.files?.[0];if(!file)return;setLoading(true);setError('');
      try{await background.upload(file)}catch(error){setError((error as Error).message)}finally{setLoading(false);e.target.value=''}
    }}/>
    {background.wallpapers.length>0&&<><h3 className="saved-wallpapers-title">Suas imagens salvas</h3><div className="scene-grid saved-wallpapers">{background.wallpapers.map((wallpaper,index)=><button key={wallpaper.id} disabled={background.saving} className={'scene-option '+(background.id===wallpaper.id?'chosen':'')} aria-pressed={background.id===wallpaper.id} onClick={()=>void background.choose(wallpaper.id)}><img src={wallpaper.url} alt="" loading="lazy"/><span>Minha foto {index+1}{background.id===wallpaper.id&&<Check size={15}/>}</span></button>)}</div></>}
    <button className="upload-button" disabled={loading||background.saving} onClick={()=>input.current?.click()}><Upload size={20}/><span><strong>{loading?'Salvando imagem…':'Escolher foto do computador'}</strong><small>JPG, PNG ou WebP · até 12 MB</small></span></button>
    <p className="privacy-copy"><ShieldCheck size={14}/>{background.saving?'Salvando no servidor…':'Imagens e escolha de fundo salvas no servidor, disponíveis nos seus outros navegadores.'}</p>
    {(error||background.storageError)&&<p role="alert" className="error">{error||background.storageError}</p>}
    <div className="dialog-bottom"><button className="quiet-button" disabled={background.saving} onClick={()=>void background.choose(scenes[0].id)}>Restaurar fundo padrão</button><button className="solid-button" disabled={loading||background.saving} onClick={onClose}>Concluir</button></div>
  </dialog>;
}

function Navigation({open,onClose,page,onPage,onBackground,connected,syncing,onRefresh,onLogout}:{open:boolean;onClose:()=>void;page:string;onPage:(page:string)=>void;onBackground:()=>void;connected:boolean;syncing:boolean;onRefresh:()=>void;onLogout:()=>void}){
  const dialog=useRef<HTMLDialogElement>(null);
  useEffect(()=>{if(open)dialog.current?.showModal();else dialog.current?.close()},[open]);
  const navigate=(key:string)=>{onPage(key);onClose()};
  return <dialog id="dashboard-menu" ref={dialog} className="navigation-drawer" aria-labelledby="navigation-title" onCancel={onClose} onClose={onClose} onClick={e=>{if(e.target===e.currentTarget)onClose()}}>
    <div className="drawer-heading"><h2 id="navigation-title">Seu ambiente</h2><button className="icon-button" aria-label="Fechar menu" onClick={onClose}><X size={20}/></button></div>
    <nav aria-label="Páginas do dashboard"><button aria-current={page==='overview'?'page':undefined} onClick={()=>navigate('overview')}><LayoutDashboard size={18}/>Visão geral</button><button aria-current={page==='history'?'page':undefined} onClick={()=>navigate('history')}><History size={18}/>Histórico</button><button aria-current={page==='diagnostics'?'page':undefined} onClick={()=>navigate('diagnostics')}><Activity size={18}/>Diagnóstico</button></nav>
    <div className="drawer-section"><span>PERSONALIZAR</span><button onClick={()=>{onClose();onBackground()}}><ImagePlus size={18}/>Papel de parede</button></div>
    <div className="drawer-section"><span>CONEXÃO E CONTA</span><button disabled={syncing} onClick={()=>{onRefresh();onClose()}}><RefreshCw size={18} className={syncing?'spinning':''}/>{syncing?'Consultando…':'Atualizar dados'}</button><button onClick={()=>{onClose();onLogout()}}><LogOut size={18}/>Sair da conta</button></div>
    <div className={'drawer-status '+(connected?'connected':'')}><i/>{connected?'Dashboard conectado':'Reconectando…'}</div>
  </dialog>;
}

function App(){
  const [backgroundOpen,setBackgroundOpen]=useState(false),[menuOpen,setMenuOpen]=useState(false);
  const [logged,setLogged]=useState(false), [checking,setChecking]=useState(true), [error,setError]=useState('');
  const background=useBackground(logged,csrf);
  const [devices,setDevices]=useState<Device[]>([]), [page,setPage]=useState('overview'), [connected,setConnected]=useState(false);
  const [period,setPeriod]=useState(1), [selected,setSelected]=useState(''), [mode,setMode]=useState('both');
  const [points,setPoints]=useState<ChartPoint[]>([]), [historyLoading,setHistoryLoading]=useState(false), [chartError,setChartError]=useState('');
  const [diagnostics,setDiagnostics]=useState<Diagnostics|null>(null), [commands,setCommands]=useState<Record<string,Command>>({}), [busy,setBusy]=useState<Record<string,boolean>>({});
  const [syncing,setSyncing]=useState(false), [imageFailed,setImageFailed]=useState(false);
  const generation=useRef(0);
  useEffect(()=>setImageFailed(false),[background.url]);
  useEffect(()=>{
    api<{csrf_token:string}>('/auth/session').then(s=>{csrf=s.csrf_token;setLogged(true)}).catch(()=>{}).finally(()=>setChecking(false));
    const expired=()=>{setLogged(false);csrf=''};window.addEventListener('session-expired',expired);return()=>window.removeEventListener('session-expired',expired);
  },[]);
  const refresh=useCallback(async()=>{try{setDevices(await api<Device[]>('/devices'));setError('')}catch(e){setError((e as Error).message)}},[]);
  useEffect(()=>{
    if(!logged)return;
    let socket:WebSocket|null=null, timer:ReturnType<typeof setTimeout>, closed=false;
    const connect=()=>{
      if(closed)return;
      socket=new WebSocket((location.protocol==='https:'?'wss:':'ws:')+'//'+location.host+'/api/v1/events');
      socket.onopen=()=>{setConnected(true);void refresh()};
      socket.onmessage=e=>{const msg=JSON.parse(e.data);if(msg.type==='snapshot')setDevices(msg.devices)};
      socket.onclose=()=>{setConnected(false);if(!closed)timer=setTimeout(connect,3000)};
      socket.onerror=()=>socket?.close();
    };
    void refresh();connect();return()=>{closed=true;clearTimeout(timer);socket?.close()};
  },[logged,refresh]);
  useEffect(()=>{
    if(!logged)return;
    const tick=()=>api<Diagnostics>('/status').then(setDiagnostics).catch(e=>setError(e.message));
    void tick();const timer=setInterval(tick,15000);return()=>clearInterval(timer);
  },[logged]);
  const sensors=devices.filter(d=>d.capabilities.includes('temperature')||d.capabilities.includes('humidity'));
  const controlled=devices.filter(d=>d.controllable||d.kind==='ir'||d.kind==='device');
  useEffect(()=>{if(!selected&&sensors.length)setSelected(sensors[0].id)},[devices,selected]);
  const loadHistory=useCallback(async()=>{
    if(!selected||!logged)return;
    const id=++generation.current;setHistoryLoading(true);setChartError('');
    const end=new Date(), start=new Date(end.getTime()-period*86400000);
    try{
      const query=(property:string)=>new URLSearchParams({property,start:start.toISOString(),end:end.toISOString(),aggregation:'hour'});
      const [temp,humidity]=await Promise.all([
        api<{points:Point[]}>('/devices/'+encodeURIComponent(selected)+'/history?'+query('temperature')),
        api<{points:Point[]}>('/devices/'+encodeURIComponent(selected)+'/history?'+query('humidity'))
      ]);
      const combined=new Map<number,ChartPoint>();
      temp.points.forEach(p=>combined.set(p.time,{time:p.time,temperature:p.value,humidity:null}));
      humidity.points.forEach(p=>combined.set(p.time,{...(combined.get(p.time)||{time:p.time,temperature:null,humidity:null}),humidity:p.value}));
      if(generation.current===id)setPoints([...combined.values()].sort((a,b)=>a.time-b.time));
    }catch(e){if(generation.current===id){setPoints([]);setChartError((e as Error).message)}}
    finally{if(generation.current===id)setHistoryLoading(false)}
  },[selected,period,logged]);
  useEffect(()=>{void loadHistory();const timer=setInterval(()=>void loadHistory(),60000);return()=>{clearInterval(timer);generation.current++}},[loadHistory]);
  async function send(device:Device,power:boolean){
    setBusy(b=>({...b,[device.id]:true}));setError('');
    try{
      const result=await api<Command>('/devices/'+encodeURIComponent(device.id)+'/commands',{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({power})});
      setCommands(c=>({...c,[device.id]:result}));await refresh();
    }catch(e){setError((e as Error).message)}finally{setBusy(b=>({...b,[device.id]:false}))}
  }
  async function synchronize(){
    setSyncing(true);setError('');
    try{setDevices(await api<Device[]>('/devices/sync',{method:'POST'}));await loadHistory()}
    catch(e){setError((e as Error).message)}finally{setSyncing(false)}
  }
  async function logout(){
    try{await api('/auth/logout',{method:'POST'});setLogged(false)}catch(e){setError((e as Error).message)}
  }
  const device=sensors.find(d=>d.id===selected)||sensors[0];
  const temperature=device?.states.find(s=>s.property==='temperature');
  const humidity=device?.states.find(s=>s.property==='humidity');
  const latest=Math.max(temperature?.observed||0,humidity?.observed||0);
  const hasPoints=points.some(p=>p.temperature!==null||p.humidity!==null);
  return <div className="spatial-app">
    <div className="room-backdrop">{!imageFailed&&<img src={background.url} alt="" onError={()=>setImageFailed(true)}/>}</div><div className="room-vignette"/>
    {logged&&<><button className="hamburger-button" aria-label="Abrir menu" aria-haspopup="dialog" aria-expanded={menuOpen} aria-controls="dashboard-menu" onClick={()=>setMenuOpen(true)}><Menu size={22}/></button><Navigation open={menuOpen} onClose={()=>setMenuOpen(false)} page={page} onPage={setPage} onBackground={()=>setBackgroundOpen(true)} connected={connected} syncing={syncing} onRefresh={()=>void synchronize()} onLogout={()=>void logout()}/><BackgroundDialog open={backgroundOpen} onClose={()=>setBackgroundOpen(false)} background={background}/></>}
    {checking?<div className="glass-well loading"><Radio size={22}/>Conectando ao seu espaço…</div>:!logged?<Login onLogin={()=>setLogged(true)}/>:<div className="spatial-layout">
      {error&&<div className="error" role="alert">{error}</div>}
      {imageFailed&&<div className="image-notice">A imagem não carregou. Você pode escolher outro cenário ou uma foto sua.</div>}
      {page!=='diagnostics'&&<main className={'spatial-window '+(page==='history'?'history-view':'')}>
        {page==='overview'&&<section className="glass-well thermostat-panel">
          <div className="panel-header-tag"><span>Clima interno</span><span className="room-badge">{device?.virtual?'Sensor virtual':'Sensor principal'}</span></div>
          <Dial temperature={temperature?Number(temperature.value):undefined}/>
          <h2 className="sensor-name">{device?.name||'Aguardando sensor'}</h2>
          <div className="reading-origin"><Cloud size={13}/>{device?.virtual?'Valores simulados na Tuya Cloud':'Valores recebidos da Tuya Cloud'}</div>
          <div className="mini-stats"><div><span>Umidade</span><strong>{number(humidity?Number(humidity.value):undefined)}<small>%</small></strong></div><div><span>Consulta</span><strong>{latest?clock(latest):'—'}</strong></div><div><span>Origem</span><strong>{device?.virtual?'Virtual':'Tuya'}</strong></div></div>
          <p className="freshness">{temperature?.stale||humidity?.stale?'A última consulta está desatualizada.':device?.cloud_snapshot_without_timestamp?'A API não informa o horário da medição.':'Horário da última atualização disponível.'}</p>
        </section>}
        <div className="right-column">
          {page==='overview'&&<div className="top-spectrum-grid"><TemperatureRangeCard deviceId={device?.id} updatedAt={temperature?.observed}/><OutdoorCard/></div>}
          <section className="glass-well chart-well">
            <div className="chart-heading"><div><p className="eyebrow">AO LONGO DO TEMPO</p><h2>O ritmo do seu ambiente.</h2></div>
              <div className="period-selector" aria-label="Período do histórico">{[1,7,30].map(p=><button key={p} aria-pressed={period===p} className={period===p?'active':''} onClick={()=>setPeriod(p)}>{p===1?'24h':p+'d'}</button>)}</div></div>
            <div className="chart-controls"><div className="sensor-select"><GlassSelect label="Sensor" value={selected} onChange={setSelected} options={sensors.map(d=>({value:d.id,label:d.name}))}/></div>
              <div className="chart-filters" aria-label="Medições no gráfico">{[['both','Tudo'],['temperature','Temp.'],['humidity','Umid.']].map(([key,label])=><button aria-pressed={mode===key} key={key} className={mode===key?'active':''} onClick={()=>setMode(key)}>{label}</button>)}</div></div>
            {chartError?<div className="chart-empty" role="alert">{chartError}</div>:!hasPoints?<div className="chart-empty">{historyLoading?'Carregando histórico…':'As medições aparecerão aqui assim que forem recebidas.'}</div>:
              <div className="chart-canvas"><ResponsiveContainer width="100%" height={208}><LineChart data={points} margin={{top:14,right:0,bottom:0,left:-18}}>
                <CartesianGrid stroke="rgba(255,255,255,.09)" vertical={false}/><XAxis dataKey="time" tickFormatter={t=>clock(Number(t))} minTickGap={50} tick={{fontSize:10,fill:'rgba(255,255,255,.55)'}} axisLine={false} tickLine={false}/>
                <YAxis yAxisId="temperature" hide={mode==='humidity'} domain={['auto','auto']} tick={{fontSize:10,fill:'#f3c58e'}} axisLine={false} tickLine={false} width={42} unit="°"/>
                <YAxis yAxisId="humidity" orientation="right" hide={mode==='temperature'} domain={[0,100]} tick={{fontSize:10,fill:'#91dcd8'}} axisLine={false} tickLine={false} width={40} unit="%"/>
                <Tooltip labelFormatter={t=>time(Number(t))} contentStyle={{background:'rgba(24,30,34,.96)',border:'1px solid rgba(255,255,255,.2)',borderRadius:14,fontSize:11,color:'#fff'}} formatter={(v:number,name:string)=>[number(v)+(name==='Temperatura'?' °C':'%'),name]}/>
                {mode!=='humidity'&&<Line yAxisId="temperature" name="Temperatura" type="linear" dataKey="temperature" stroke="#f1c791" strokeWidth={2.3} dot={false} connectNulls={false} isAnimationActive={false}/>}
                {mode!=='temperature'&&<Line yAxisId="humidity" name="Umidade" type="linear" dataKey="humidity" stroke="#88d7d4" strokeWidth={2.3} dot={false} connectNulls={false} isAnimationActive={false}/>}
              </LineChart></ResponsiveContainer></div>}
            <div className="chart-legend">{mode!=='humidity'&&<span><i className="temp-dot"/>Temperatura</span>}{mode!=='temperature'&&<span><i className="humidity-dot"/>Umidade</span>}</div>
            <p className="chart-note">Médias por hora · lacunas sem interpolação{device?.cloud_snapshot_without_timestamp?' · horários de consulta':''}</p>
          </section>
        </div>
      </main>}
      {page==='overview'&&controlled.length>0&&<section className="appliances">{controlled.map(d=>{
        const power=d.states.find(s=>s.property==='power'), command=commands[d.id]||d.last_command;
        return <article key={d.id} className="glass-well appliance"><div className="appliance-heading"><Zap size={20}/><span>{d.connectivity}</span></div><h2>{d.name}</h2>
          <p>{power?(power.value?'Ligado':'Desligado')+' · '+power.source:'Estado desconhecido'}</p>
          <div className="command-buttons"><button disabled={!d.controllable||busy[d.id]} onClick={()=>void send(d,true)}><Power size={14}/>Ligar</button><button disabled={!d.controllable||busy[d.id]} onClick={()=>void send(d,false)}><Power size={14}/>Desligar</button></div>
          <p role="status">{busy[d.id]?'Enviando…':command?'Último comando: '+command.status:d.controllable?'Pronto para comandos':'Controle ainda não validado'}</p>
          {d.kind==='ir'&&<small>O infravermelho não confirma o estado físico.</small>}
        </article>;
      })}</section>}
      {page==='diagnostics'&&<main className="spatial-window diagnostic-window"><section className="glass-well diagnostic">
        <div className="chart-heading"><div><p className="eyebrow">SAÚDE DA CONEXÃO</p><h2>Seu ambiente, conectado.</h2></div><Activity size={23}/></div>
        {diagnostics?<><div className="diagnostic-grid">{[
          ['Tuya Cloud',diagnostics.tuya_connected?'Conectada':'Sem conexão de eventos'],['Eventos pendentes',diagnostics.pending],
          ['Falhas de processamento',diagnostics.dead],['Comandos sem confirmação',diagnostics.commands_unknown],['Consultas neste minuto',diagnostics.http_calls_window],
          ['Última ingestão',diagnostics.health.last_ingest?.at?time(Number(diagnostics.health.last_ingest.at)):'Aguardando']
        ].map(([label,value])=><div key={String(label)}><span>{label}</span><strong>{value}</strong></div>)}</div><details><summary>Detalhes dos serviços</summary><pre>{JSON.stringify(diagnostics.health,null,2)}</pre></details></>:<p>Carregando diagnóstico…</p>}
      </section></main>}
      <footer className="spatial-footer"><span><ShieldCheck size={12}/>Integração privada com a Tuya</span><span>{latest?'Consulta à nuvem · '+time(latest):'Aguardando dados'} · São Paulo</span></footer>
      <div className="vision-grabber" aria-hidden="true"/>
    </div>}
  </div>;
}

function Login({onLogin}:{onLogin:()=>void}){
  const [password,setPassword]=useState(''), [error,setError]=useState(''), [busy,setBusy]=useState(false);
  return <main className="login-window"><form className="glass-well login-form" onSubmit={async e=>{
    e.preventDefault();setBusy(true);setError('');
    try{const data=await api<{csrf_token:string}>('/auth/login',{method:'POST',body:JSON.stringify({username:'admin',password})});csrf=data.csrf_token;onLogin()}
    catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }}>
    <div className="login-logo"><Radio size={28}/></div><h1>Entre no seu espaço.</h1><p className="login-copy">O clima do seu ambiente, sob uma nova perspectiva.</p>
    <label htmlFor="password">Senha do administrador</label><input id="password" type="password" autoComplete="current-password" required value={password} onChange={e=>setPassword(e.target.value)}/>
    {error&&<p role="alert" className="error">{error}</p>}
    <button className="solid-button login-submit" disabled={busy}>{busy?'Entrando…':'Acessar ambiente'}<ArrowUpRight size={18}/></button><small><ShieldCheck size={13}/>Acesso protegido à sua rede interna</small>
  </form></main>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
