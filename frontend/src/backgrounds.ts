import {useEffect, useRef, useState} from 'react';

export const scenes = [
  {id:'solar',name:'Sala Solar',url:'https://images.unsplash.com/photo-1600210492486-724fe5c67fb0?auto=format&fit=crop&w=2000&q=85'},
  {id:'studio',name:'Estúdio',url:'https://images.unsplash.com/photo-1618221195710-dd6b41faaea6?auto=format&fit=crop&w=2000&q=85'},
  {id:'nordic',name:'Luz Nórdica',url:'https://images.unsplash.com/photo-1513694203232-719a280e022f?auto=format&fit=crop&w=2000&q=85'}
];
type Appearance = {selected:string;wallpapers:{id:string;name:string;url:string}[]};
const initial:Appearance={selected:'solar',wallpapers:[]};

export function useBackground(logged:boolean,csrf:string) {
  const [preference,setPreference]=useState<Appearance>(initial),[storageError,setStorageError]=useState(''),[saving,setSaving]=useState(false);
  const busy=useRef(false),revision=useRef(0);
  async function request(init:RequestInit={}){
    const response=await fetch('/api/v1/appearance'+(init.method==='POST'?'/wallpapers':''),{...init,credentials:'same-origin',headers:{'X-CSRF-Token':csrf,...init.headers}});
    if(response.status===401)window.dispatchEvent(new Event('session-expired'));
    if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.detail||'Não foi possível salvar o papel de parede no servidor.')}
    return response.json() as Promise<Appearance>;
  }
  useEffect(()=>{
    if(!logged){setPreference(initial);return}
    let active=true;
    const load=async()=>{
      if(busy.current)return;
      const current=++revision.current;
      try{const data=await request();if(active&&current===revision.current&&!busy.current){setPreference(data);setStorageError('')}}
      catch(e){if(active&&current===revision.current)setStorageError((e as Error).message)}
    };
    void load();const timer=setInterval(()=>void load(),30000);
    window.addEventListener('focus',load);
    return()=>{active=false;clearInterval(timer);window.removeEventListener('focus',load)};
  },[logged,csrf]);
  async function save(init:RequestInit){
    if(busy.current)throw new Error('Aguarde o salvamento atual.');
    revision.current++;busy.current=true;setSaving(true);setStorageError('');
    try{setPreference(await request(init))}
    catch(e){setStorageError((e as Error).message);throw e}
    finally{busy.current=false;setSaving(false)}
  }
  async function choose(id:string){
    try{await save({method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})})}catch{/* Error is displayed in the dialog. */}
  }
  async function upload(file:File){
    if(!['image/jpeg','image/png','image/webp'].includes(file.type))throw new Error('Escolha uma imagem JPG, PNG ou WebP.');
    if(file.size>12*1024*1024)throw new Error('Escolha uma imagem de até 12 MB.');
    let bitmap:ImageBitmap;
    try{bitmap=await createImageBitmap(file)}catch{throw new Error('Não foi possível abrir esta imagem.')}
    try{
      const scale=Math.min(1,1920/Math.max(bitmap.width,bitmap.height));
      const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(bitmap.width*scale));canvas.height=Math.max(1,Math.round(bitmap.height*scale));
      const ctx=canvas.getContext('2d');if(!ctx)throw new Error('Não foi possível preparar a imagem.');
      ctx.fillStyle='#1b2025';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(bitmap,0,0,canvas.width,canvas.height);
      const blob=await new Promise<Blob>((resolve,reject)=>canvas.toBlob(b=>b?resolve(b):reject(new Error('Não foi possível preparar a imagem.')),'image/jpeg',.85));
      if(blob.size>3*1024*1024)throw new Error('Escolha uma versão menor da imagem.');
      await save({method:'POST',headers:{'Content-Type':'image/jpeg'},body:blob});
    }finally{bitmap.close()}
  }
  return {id:preference.selected,url:scenes.find(s=>s.id===preference.selected)?.url||preference.wallpapers.find(w=>w.id===preference.selected)?.url||scenes[0].url,
    wallpapers:preference.wallpapers,choose,upload,storageError,saving};
}

