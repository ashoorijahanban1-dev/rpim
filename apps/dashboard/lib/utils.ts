// 21st.dev / shadcn-standard class utility (ADR 0040): every drop-in
// component from that ecosystem imports `cn` from "@/lib/utils".
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
