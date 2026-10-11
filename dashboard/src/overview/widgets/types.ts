import type { ComponentType, LazyExoticComponent, ReactNode } from "react";
import type { SettingName, WidgetSettings, WidgetSize, WidgetType } from "../catalog";

export interface WidgetProps {
  projectId: number;
  /** The stored settings over the widget's defaults, each one valid. An absent `branch` means every branch. */
  settings: WidgetSettings;
  size: WidgetSize;
  /** The card's h2, a link to the full view (spec §2.7): the widget places it, first or in a head row with a badge. */
  heading: ReactNode;
  /** Opens this widget's settings (the empty-branch and no-name buttons); absent where that is not possible. */
  onOpenSettings?: () => void;
}

/** One widget type (plan Ruling 17): this metadata lives in `widgets/<type>.ts`, the component in its own chunk. */
export interface WidgetDefinition {
  type: WidgetType;
  /** The name in the Add widget list, and the card title unless `cardTitle` says otherwise. */
  title: string;
  description: string;
  defaultSize: WidgetSize;
  /** Exactly the catalogue's settings for this type (registry.test.ts checks it). */
  settings: SettingName[];
  defaults: WidgetSettings;
  cardTitle?: (settings: WidgetSettings) => string;
  /** Code-split: loads only when a layout places the widget. */
  Component: LazyExoticComponent<ComponentType<WidgetProps>>;
  /** The full view with the same filters (spec §2.7). */
  link: (projectId: number, settings: WidgetSettings) => string;
}
