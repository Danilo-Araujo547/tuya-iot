import React,{useEffect,useRef,useState} from 'react';
import {Check,ChevronDown} from 'lucide-react';
export function GlassSelect({label,value,options,onChange,placeholder='Selecione'}:{label:string;value:string;options:{value:string;label:string}[];onChange:(value:string)=>void;placeholder?:string}) {
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
  }}><button ref={trigger} type="button" className="glass-select-trigger" aria-label={label} aria-haspopup="listbox" aria-expanded={open} aria-controls={id} onClick={()=>setOpen(!open)}><span>{options.find(o=>o.value===value)?.label||placeholder}</span><ChevronDown size={12}/></button>
    {open&&<div id={id} role="listbox" aria-label={label} className="glass-select-menu">{options.map(option=><button type="button" role="option" aria-selected={option.value===value} key={option.value} onClick={()=>{onChange(option.value);setOpen(false);trigger.current?.focus()}}><span>{option.label}</span>{option.value===value&&<Check size={13}/>}</button>)}</div>}
  </div>;
}

