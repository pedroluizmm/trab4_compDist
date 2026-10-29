"""Deterministic corpus generator. Refuses to replace any non-matching file.
Use --check to audit without writes. Generated expected links do not use HTML parsers.
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from urllib.parse import urljoin
ROOT=Path(__file__).resolve().parents[1]


def corpus():
    files={};pages=[]
    for i in range(1,11):
        count=5 if i%2 else 50
        size=[8,16,64,128,256][(i-1)//2]*1024
        url=f'http://paginas/pagina{i:02d}.html'
        links=[];anchors=[]
        for n in range(count):
            href=[f'/destino/{i}/{n}?a=1&b=2',f'relativo-{n}.html',f'https://example.org/pagina/{i}/{n}',f'#secao-{n}',f'../raiz-{n}'][n%5]
            text=f'P\u00e1gina {i:02d} link {n:02d}' if n%7 else '[IMG]'
            inner=f'  P\u00e1gina {i:02d}\n   link {n:02d}  ' if n%7 else '<img src="icone.svg" alt="icone">'
            anchors.append(f'<a href="{href.replace("&","&amp;")}">{inner}</a>')
            links.append({'text':text,'href':urljoin(url,href)})
        prefix=f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Pagina {i:02d}</title></head><body><h1 id="pagina{i:02d}">Corpus {i:02d}</h1>'+'\n'.join(anchors)+'<!--'
        suffix='--></body></html>\n'
        body=(prefix+'x'*(size-len((prefix+suffix).encode()))+suffix).encode()
        assert len(body)==size
        filename=f'pagina{i:02d}.html'
        files['paginas-teste/html/'+filename]=body
        pages.append(dict(id=f'pagina{i:02d}',url=url,filename=filename,size_bytes=size,
            sha256=hashlib.sha256(body).hexdigest(),expected_count=count,expected_links=links))
    files['paginas-teste/manifest.json']=(json.dumps(pages,ensure_ascii=False,indent=2)+'\n').encode()
    stream=io.StringIO(newline='')
    w=csv.DictWriter(stream,fieldnames=['id','url','size_bytes','expected_count','sha256'])
    w.writeheader();w.writerows({k:p[k] for k in w.fieldnames} for p in pages)
    files['paginas-teste/inventario.csv']=stream.getvalue().encode()
    return files


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    files=corpus()
    for name,body in files.items():
        p=ROOT/name
        if p.exists():
            actual=p.read_bytes()
            if p.suffix=='.json':actual=actual.replace(b'\r\n',b'\n')
            if actual!=body:raise RuntimeError(f'Non-matching file, will not overwrite: {p}')
        elif args.check:raise FileNotFoundError(p)
        else:p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(body)
    print('Corpus verified: 10 distinct pages and matching independent manifest.')

if __name__=='__main__':main()
