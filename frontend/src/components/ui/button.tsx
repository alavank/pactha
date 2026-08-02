import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

// daisyUI `btn` como base. Mantém a API (variant/size) usada em todo o app.
const buttonVariants = cva(
  "btn normal-case font-medium [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        /* QUASE PRETO, nao menta. A regra esta escrita em globals.css desde
           o inicio desta identidade ("o botao preenchido do Painel e quase
           preto, 18,53 de contraste; fica em `neutral`") — mas o `<Button>`
           padrao continuou em `btn-primary`, entao o botao principal de oito
           telas era VERDE. Eu vinha corrigindo um a um nas telas que migrava
           e nunca corrigi a origem: mesmo erro dos modais.
           `neutral` aponta para `--bi-cta` nos dois temas. */
        default: "btn-neutral",
        outline: "btn-outline border-base-300 text-base-content hover:border-primary hover:bg-base-200",
        secondary: "btn-secondary",
        ghost: "btn-ghost",
        destructive: "btn-error btn-soft",
        link: "btn-link text-primary",
      },
      size: {
        default: "btn-sm",
        xs: "btn-xs",
        sm: "btn-sm",
        lg: "btn-md",
        icon: "btn-sm btn-square",
        "icon-xs": "btn-xs btn-square",
        "icon-sm": "btn-sm btn-square",
        "icon-lg": "btn-md btn-square",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants>) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
