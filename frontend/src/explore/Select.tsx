import * as SelectPrimitive from "@radix-ui/react-select";
import { Children, isValidElement, useEffect, useRef, useState, type ComponentProps, type ReactNode } from "react";
import { Check, ChevronDown, ChevronUp } from "lucide-react";

type Props = Pick<ComponentProps<"button">, "id" | "aria-label" | "aria-describedby" | "title" | "disabled" | "className"> & {
  value: string | number;
  onValueChange: (value: string) => void;
  children: ReactNode;
};

// Prefix every value so empty filter/assignment values remain selectable in Radix.
const encode = (value: string | number) => `option:${value}`;

/** One presentation boundary for the app's single-choice fields. Children are plain options. */
export function Select({ value, onValueChange, children, className = "", disabled, ...props }: Props) {
  const trigger = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);
  useEffect(() => {
    if (!disabled && restoreFocus.current) {
      restoreFocus.current = false;
      // A save may temporarily disable the trigger during menu dismissal.
      if (document.activeElement === document.body) trigger.current?.focus();
    }
  }, [disabled]);
  const [container, setContainer] = useState<HTMLElement | null>(null);
  const options = Children.toArray(children).filter(isValidElement<ComponentProps<"option">>).map(child => ({
    value: String(child.props.value ?? child.props.children),
    label: child.props.children,
    disabled: child.props.disabled,
  }));
  return <SelectPrimitive.Root value={encode(value)} disabled={disabled} onValueChange={next => onValueChange(next.slice(7))}
    onOpenChange={open => {
      // Keep menus inside native top-layer dialogs/popovers, and within theme scope.
      if (open) setContainer(trigger.current?.closest<HTMLElement>("[popover], dialog, .explore") ?? null);
    }}>
    <SelectPrimitive.Trigger {...props} ref={trigger} className={`ex-select ${className}`} data-value={String(value)}>
      <SelectPrimitive.Value />
      <SelectPrimitive.Icon className="ex-select-chevron"><ChevronDown size={15} aria-hidden="true" /></SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
    <SelectPrimitive.Portal container={container}>
      <SelectPrimitive.Content className="ex-select-menu" position="popper" sideOffset={6} collisionPadding={12}
        onCloseAutoFocus={event => {
          if (trigger.current?.matches(":disabled")) {
            event.preventDefault();
            restoreFocus.current = true;
          }
        }}
        onEscapeKeyDown={event => {
          // Close only this menu; a second Escape can dismiss its parent dialog/popover.
          event.stopPropagation();
        }}>
        <SelectPrimitive.ScrollUpButton className="ex-select-scroll"><ChevronUp size={15} /></SelectPrimitive.ScrollUpButton>
        <SelectPrimitive.Viewport className="ex-select-options">
          {options.map(option => <SelectPrimitive.Item className="ex-select-option" key={option.value}
            value={encode(option.value)} data-value={option.value} disabled={option.disabled}>
            <SelectPrimitive.ItemText>{option.label}</SelectPrimitive.ItemText>
            <SelectPrimitive.ItemIndicator className="ex-select-check"><Check size={15} /></SelectPrimitive.ItemIndicator>
          </SelectPrimitive.Item>)}
        </SelectPrimitive.Viewport>
        <SelectPrimitive.ScrollDownButton className="ex-select-scroll"><ChevronDown size={15} /></SelectPrimitive.ScrollDownButton>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  </SelectPrimitive.Root>;
}
