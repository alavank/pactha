import { TabBar } from "@/components/TabBar";

// Shell do app mobile: coluna estreita centrada (bom no celular e no desktop),
// com a tab bar fixa no rodapé.
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-[480px] min-h-dvh bg-page px-4 pt-2 pb-28">
      {children}
      <TabBar />
    </div>
  );
}
