import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.zip.*;
import javax.xml.stream.*;

/** Extracts textual content and paragraph boundaries from the DOCX main document part. */
class WordText {
    public static void main(String[] args) throws Exception {
        if (args.length != 2) throw new IllegalArgumentException("Input and output required");
        XMLInputFactory factory = XMLInputFactory.newFactory();
        factory.setProperty(XMLInputFactory.SUPPORT_DTD, false);
        factory.setProperty(XMLInputFactory.IS_SUPPORTING_EXTERNAL_ENTITIES, false);
        try (ZipFile zip = new ZipFile(args[0]);
             InputStream input = zip.getInputStream(zip.getEntry("word/document.xml"));
             BufferedWriter out = Files.newBufferedWriter(Path.of(args[1]), StandardCharsets.UTF_8)) {
            XMLStreamReader reader = factory.createXMLStreamReader(input);
            while (reader.hasNext()) {
                int event = reader.next();
                if (event != XMLStreamConstants.START_ELEMENT && event != XMLStreamConstants.END_ELEMENT) continue;
                String namespace = reader.getNamespaceURI();
                if (!"http://schemas.openxmlformats.org/wordprocessingml/2006/main".equals(namespace)
                    && !"http://purl.oclc.org/ooxml/wordprocessingml/main".equals(namespace)) continue;
                String tag = reader.getLocalName();
                if (event == XMLStreamConstants.START_ELEMENT) {
                    switch (tag) {
                        case "t" -> out.write(reader.getElementText());
                        case "tab" -> out.write('\t');
                        case "br", "cr" -> out.write('\n');
                    }
                } else if (tag.equals("p")) out.write('\n');
            }
            reader.close();
        }
    }
}
