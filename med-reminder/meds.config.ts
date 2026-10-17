import type { Config } from "./src/config";

// Your schedule. Edit this file, run `npm run deploy`, done.
// Note: if this folder lives in a public repo, these med names are public too.
export const config: Config = {
  timezone: "Asia/Kolkata",
  nagIntervalMin: 10,
  emailFallbackAfterMin: 30,
  escalateAfterMin: 90,
  defaultMaxLateMin: 240,
  digestTime: "22:00",

  meds: [
    { name: "Metformin 500mg", times: ["08:00", "20:00"], note: "with food" },
    { name: "Vitamin D", times: ["09:00"], days: ["mon", "thu"] },
    // Some meds shouldn't be taken very late — after maxLateMin the bot stops and logs it as missed.
    { name: "Thyroxine", times: ["06:30"], note: "empty stomach", maxLateMin: 120 },
  ],
};
