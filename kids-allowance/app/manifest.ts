import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "おこづかいちょう",
    short_name: "おこづかい",
    description: "咲太朗と芽依のおこづかい記録帳",
    start_url: "/",
    display: "standalone",
    background_color: "#FFF8EF",
    theme_color: "#FF8FA3",
    icons: [
      {
        src: "/icon-192.png",
        sizes: "180x180",
        type: "image/png",
      },
      {
        src: "/icon-512.png",
        sizes: "256x256",
        type: "image/png",
      },
    ],
  };
}
