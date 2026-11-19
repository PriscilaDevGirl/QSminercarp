import com.sun.source.tree.ClassTree;
import com.sun.source.tree.CompilationUnitTree;
import com.sun.source.tree.MethodTree;
import com.sun.source.util.JavacTask;
import com.sun.source.util.SourcePositions;
import com.sun.source.util.TreePathScanner;
import com.sun.source.util.Trees;
import javax.tools.Diagnostic;
import javax.tools.DiagnosticCollector;
import javax.tools.JavaFileObject;
import javax.tools.StandardJavaFileManager;
import javax.tools.ToolProvider;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.stream.Collectors;

class InspectJava {
    public static void main(String[] args) throws Exception {
        List<String> items = Files.readAllLines(Path.of(args[1]), StandardCharsets.UTF_8);
        extractMethods(items, Charset.forName(args[2]));
    }

    private static void extractMethods(List<String> paths, Charset charset) throws Exception {
        var compiler = ToolProvider.getSystemJavaCompiler();
        var diagnostics = new DiagnosticCollector<JavaFileObject>();
        try (StandardJavaFileManager manager = compiler.getStandardFileManager(diagnostics, null, charset)) {
            var sources = manager.getJavaFileObjectsFromStrings(paths);
            var task = (JavacTask) compiler.getTask(null, manager, diagnostics,
                    List.of("-proc:none"), null, sources);
            SourcePositions positions = Trees.instance(task).getSourcePositions();
            for (CompilationUnitTree unit : task.parse()) {
                new TreePathScanner<Void, String>() {
                    @Override public Void visitClass(ClassTree node, String owner) {
                        String simple = node.getSimpleName().toString();
                        if (simple.isEmpty()) {
                            simple = "<anonymous@" + unit.getLineMap()
                                    .getLineNumber(positions.getStartPosition(unit, node)) + ">";
                        }
                        boolean top = getCurrentPath().getParentPath().getLeaf() == unit;
                        String separator = top ? "." : "$";
                        return super.visitClass(node, owner.isEmpty() ? simple : owner + separator + simple);
                    }

                    @Override public Void visitMethod(MethodTree method, String owner) {
                        long start = positions.getStartPosition(unit, method);
                        long end = positions.getEndPosition(unit, method);
                        if (start >= 0 && end > start) {
                            String parameters = method.getParameters().stream()
                                    .map(p -> p.getType().toString().replaceAll("\\s+", " "))
                                    .collect(Collectors.joining(","));
                            System.out.printf("METHOD\t%s\t%d\t%d\t%s#%s(%s)%n",
                                    Path.of(unit.getSourceFile().toUri()),
                                    unit.getLineMap().getLineNumber(start),
                                    unit.getLineMap().getLineNumber(end - 1),
                                    owner, method.getName(), parameters);
                        }
                        return super.visitMethod(method, owner);
                    }
                }.scan(unit, unit.getPackageName() == null ? "" : unit.getPackageName().toString());
            }
        }
        for (var diagnostic : diagnostics.getDiagnostics()) {
            if (diagnostic.getKind() == Diagnostic.Kind.ERROR) {
                System.err.println(diagnostic);
            }
        }
        if (diagnostics.getDiagnostics().stream().anyMatch(d -> d.getKind() == Diagnostic.Kind.ERROR)) {
            System.exit(2);
        }
    }
}
