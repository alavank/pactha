import * as React from "react"
import { Input as InputPrimitive } from "@base-ui/react/input"

import { cn } from "@/lib/utils"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <InputPrimitive
      type={type}
      data-slot="input"
      className={cn(
        "h-9 w-full rounded-lg border border-transparent bg-base-200 px-3 text-sm text-base-content placeholder:text-base-content/40 transition focus:border-primary focus:bg-base-100 focus:ring-2 focus:ring-primary/15 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    />
  )
}

export { Input }
