# Sample video

`stereo-overview-60s.mp4` is the first 60 seconds of **"STEREO overview 2011-02-06"**, transcoded from Ogg Theora/Vorbis to H.264/AAC MP4 with FFmpeg (video re-encoded, nothing else changed).

- Author: NASA GSFC
- Original: https://commons.wikimedia.org/wiki/File:STEREO_overview_2011-02-06.ogv
- NASA source page (as listed on Commons): https://www.nasa.gov/multimedia/videogallery/index.html?media_id=59678391
- License: **Public domain** in the United States (work of NASA; Wikimedia Commons license template PD-USGov). NASA copyright policy: "NASA material is not protected by copyright unless noted." https://www.nasa.gov/nasa-brand-center/images-and-media/
- Note: use of NASA logos and insignia is restricted. This clip is used for demonstration only and carries no endorsement by NASA.

Re-create the clip:

```bash
curl -L -o stereo.ogv "https://upload.wikimedia.org/wikipedia/commons/e/e1/STEREO_overview_2011-02-06.ogv"
ffmpeg -ss 0 -t 60 -i stereo.ogv -c:v libx264 -preset medium -crf 23 -pix_fmt yuv420p -c:a aac -b:a 96k -movflags +faststart stereo-overview-60s.mp4
```

You can use any short MP4 with clear English speech instead.
