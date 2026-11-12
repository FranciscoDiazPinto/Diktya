// Uso: node renderizar_diseno.cjs carpeta-svg carpeta-png; requiere Sharp en el entorno.
const fs=require('fs');const path=require('path');const sharp=require('sharp');
(async()=>{const src=process.argv[2],out=process.argv[3];fs.mkdirSync(out,{recursive:true});for(const file of fs.readdirSync(src).filter(x=>x.endsWith('.svg'))){await sharp(path.join(src,file)).png().toFile(path.join(out,file.replace(/\.svg$/,'.png')));}console.log('Figuras renderizadas');})();
