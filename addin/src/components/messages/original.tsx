import type { Message } from "@/models/email"
import { useState } from "react"
import { Button } from "../ui/button"
import { Eye, EyeClosed } from "lucide-react"
import { t } from "@/lib/i18n"

type Props = {
    message: Message
    index: number
}

export const OriginalEmail = ({ message }: Props) => {
    const [isCollapsed, setCollapsed] = useState(true)
    return (
        <div className="max-w-[80%] rounded-lg px-4 py-3 bg-muted text-gray-900">
            <div className="flex items-start gap-2">
                <div className="flex-1">

                    <div className="flex items-center justify-between text-xs font-medium mb-1 opacity-70 relative">
                        <span>{t('email.original')}</span>
                        <div className="absolute -right-2 -top-2">
                            <Button size={"icon-sm"} variant={"ghost"} onClick={() => setCollapsed((prev) => !prev)} >{isCollapsed ? <Eye className="size-4" /> : <EyeClosed className="size-4" />}</Button>
                        </div>
                    </div>

                    <div className="text-sm whitespace-pre-wrap wrap-break-word">
                        {isCollapsed ? "..." : message.content as string}
                    </div>
                </div>
            </div>
        </div>)
}
