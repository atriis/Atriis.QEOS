import { Component, type ErrorInfo, type ReactNode } from "react";
import ErrorBanner from "../components/ErrorBanner";

interface Props {
  heading: ReactNode;
  title: string;
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/** One widget's render failure stays in its card (spec §2.8): "This widget failed to load · Retry", and the rest of
 *  the page keeps working. Retry renders the widget again. */
export default class WidgetBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`Overview widget "${this.props.title}" failed to render`, error, info.componentStack);
  }

  render() {
    if (this.state.error === null) return this.props.children;
    return (
      <>
        {this.props.heading}
        <ErrorBanner
          error={this.state.error}
          message="This widget failed to load"
          onRetry={() => this.setState({ error: null })}
        />
      </>
    );
  }
}
