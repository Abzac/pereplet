export type ImageSize={width:number;height:number};
export type ImageView={scale:number;x:number;y:number};

/** Contain with breathing room; a small illustration is enlarged too. */
export function fitImage(image:ImageSize,canvas:ImageSize):number {
 if(image.width<=0||image.height<=0||canvas.width<=0||canvas.height<=0)return 1;
 const width=Math.max(1,canvas.width-2*Math.max(24,canvas.width*.05));
 const height=Math.max(1,canvas.height-2*Math.max(24,canvas.height*.05));
 return Math.min(width/image.width,height/image.height);
}

/** Keep the image point beneath the cursor stationary while zooming. */
export function zoomImage(view:ImageView,requested:number,cursor:{x:number;y:number},fit:number):ImageView {
 const scale=Math.max(Math.min(.1,fit*.1),Math.min(Math.max(8,fit*8),requested));
 const factor=scale/view.scale;
 return{scale,x:cursor.x-(cursor.x-view.x)*factor,y:cursor.y-(cursor.y-view.y)*factor};
}
