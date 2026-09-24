import { createTheme } from "@mantine/core";

const theme = createTheme({
  fontFamily: "Inter, system-ui, -apple-system, sans-serif",
  primaryColor: "indigo",
  defaultRadius: "md",
  headings: { fontWeight: "600" },
  // дефолтная тёмная палитра Mantine серо-стальная (dark-7 #373A40) - уводим в глубокий графит
  colors: {
    dark: [
      "#C9CDD6", "#B4B8BF", "#89909C", "#6C7380", "#5A606C",
      "#454A55", "#2B2F38", "#1B1E24", "#12141A", "#0A0B0F",
    ],
  },
});

export default theme;
