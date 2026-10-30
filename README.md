CONVERSATIONAL PREGNANCY INFORMATION ASSISTANT

A Django-Based Conversational Pregnancy Information Assistant

BSIT Class Project Concept Paper

INTRODUCTION

Background of the Project

Pregnancy is an important period that involves physical, emotional, and lifestyle changes. During pregnancy, women may have questions about common symptoms, nutrition, prenatal care, fetal development, healthy practices, and warning signs that may require medical attention. Access to understandable and reliable information can help pregnant women become better informed and prepare questions for their healthcare providers.

Although pregnancy-related information is available through websites and social media, users may find it difficult to identify information that is reliable, relevant, and easy to understand. Searching through multiple sources may also be time-consuming, especially when users want a direct explanation of a common pregnancy concern. A digital platform that organizes reviewed pregnancy information and allows users to ask questions in everyday language may help address this information-access need.

The proposed Conversational Pregnancy Information Assistant, also known as PregnaBot, will be developed as a web-based application using the Django framework. It will provide a conversational question-and-answer interface connected to a structured pregnancy knowledge base. Users will be able to ask pregnancy-related questions and receive general educational information relevant to the topic. The system will also provide source information where available and safety guidance when a question involves symptoms that may require prompt professional attention.

PregnaBot will serve as an educational information tool and will not diagnose medical conditions, prescribe medicines, or replace consultation with qualified healthcare professionals. Users who report possible warning signs will be encouraged to seek appropriate medical care.

Statement of the Problem or Project Objectives

The project will address the difficulty that some pregnant women may experience in finding understandable and organized information about common pregnancy concerns. It will aim to provide an accessible web-based conversational assistant that will present general pregnancy information from a structured knowledge base.

The general objective of the project will be to develop and evaluate a Django-based Conversational Pregnancy Information Assistant that will provide accessible, organized, and understandable pregnancy-related information through a conversational question-and-answer interface.

The specific objectives will be to:

1. Develop a web-based platform that will allow visitors to access the system as guests and allow registered users to create accounts and log in.

2. Develop a conversational interface through which users will submit pregnancy-related questions using natural, everyday language.

3. Organize pregnancy-related educational content into a structured knowledge base covering common symptoms, nutrition, prenatal care, pregnancy development, common concerns, healthy practices, and warning signs.

4. Provide relevant responses to pregnancy-related questions and display available source information to support the responses.

5. Include safety-oriented guidance that will encourage users to seek professional medical care when questions involve possible warning signs.

6. Provide registered users with pregnancy profile information and access to their saved conversation history, while guest conversations will remain session-based.

7. Provide administrative functions for managing pregnancy information, frequently asked questions, and related content.

8. Evaluate the system in terms of functionality, usability, accessibility, reliability, and response quality.

Significance of the Project

Pregnant Women.The system will offer a convenient way to access general pregnancy-related information and obtain explanations about common pregnancy questions.

First-Time Mothers.The system will serve as an additional educational resource for users who may be unfamiliar with common pregnancy changes, prenatal care, and warning signs.

Healthcare Workers.The system may serve as a supplementary information resource that organizes commonly requested pregnancy topics. It will not replace professional assessment, diagnosis, or consultation.

Researchers and Students.The project may provide a reference for students and researchers interested in developing web-based health information systems and conversational applications using Django.

Future Developers.The project may serve as a foundation for future enhancements, such as additional language support, expanded reviewed content, or integration with other appropriate health information services.

Alignment with Institutional Research Agenda and Sustainable Development Goals

Institutional Research Agenda Alignment. The project will support the institution's Information Technology and digital innovation research priorities by applying web-based technologies to improve access to organized educational information. The final wording of this alignment will be adjusted to match the institution's officially approved research agenda.

Sustainable Development Goal 3 (Good Health and Well-Being). The project will support health education by making general pregnancy-related information more accessible and by encouraging users to seek professional care when potentially concerning symptoms are identified.

Sustainable Development Goal 9 (Industry, Innovation and Infrastructure). The project will demonstrate the application of digital technology in developing an accessible web-based information service.

SCOPE AND LIMITATIONS

System Scope and Technical Architecture

The project will focus on the development and evaluation of PregnaBot, a web-based conversational pregnancy information assistant. The system will be intended for pregnant women, first-time mothers, and other users seeking general pregnancy-related educational information. It will be accessible through a web browser on supported computers, tablets, and smartphones.

The system will include the following components and functions:

User Access and Account Management.The system will provide a welcome page with guest access, user registration, and login. Guest users will be able to use a temporary session, while registered users will be able to access account-based features.

Pregnancy Profile.Registered users will be able to provide and update relevant profile information through a pregnancy profile form. The system will use the profile to support account onboarding and display the user's saved profile information; it will not generate a medical assessment.

Conversational Chatbot.Users will be able to submit pregnancy-related questions through the PregnaBot chat interface. The system will retrieve relevant information from its pregnancy knowledge base and present a conversational response.

Pregnancy Knowledge Base and Information Categories.The system will organize educational content about common pregnancy symptoms, nutrition, prenatal care, pregnancy development, common concerns, healthy practices, and warning signs. Available source information will be presented with relevant responses.

Frequently Asked Questions and Pregnancy Information.Users will be able to browse pregnancy information and frequently asked questions through the web application.

Conversation History.Registered users will be able to view and search their saved conversations. Guest conversations will be maintained only within the active session and will not be included in registered users' account history.

Safety Guidance.The system will provide safety-oriented information for questions that may involve warning signs and will direct users to seek professional medical attention when appropriate.

Administrative Content Management.Authorized administrators will be able to manage pregnancy information and related content through the administrative interface.

Technology Stack.The application will use Python and Django for backend development, HTML, CSS, JavaScript, and the project's frontend styling for the user interface, and a relational database supported by Django. The system will support the configured conversational response provider, such as OpenAI or an Ollama endpoint, subject to the project's settings and deployment environment.

Limitations

The system will provide general educational information only. It will not diagnose diseases, determine whether an individual pregnancy is medically normal or abnormal, prescribe medicines, or recommend treatment as a substitute for a healthcare professional.

The accuracy and usefulness of responses will depend on the completeness, quality, and review of the pregnancy information stored in the knowledge base and on the configured response provider. The system will not guarantee that every possible question or individual medical situation can be answered.

The system will not replace prenatal consultations, laboratory tests, emergency services, or the professional judgment of doctors, nurses, midwives, and other qualified healthcare workers.

Guest conversation context will be temporary and will not be saved as registered-user conversation history. Account-based conversation history will require users to access the system through their registered accounts.

Use of an external response provider, when configured, may involve sending the user's question and relevant retrieved pregnancy information to that provider. The system's privacy disclosures and deployment configuration will identify the applicable data handling arrangements.

Online appointment booking, direct telemedicine consultation, electronic medical record integration, SMS notifications, and automated medication prescriptions will be outside the scope of the project unless separately approved as future enhancements.

The system will require an internet or network connection and a compatible web browser in the environment where it will be deployed.

DEFINITION OF TERMS

Key Terms

Conversational Pregnancy Information Assistant.A web-based system that will allow users to submit pregnancy-related questions and receive general educational information through a conversational interface.

PregnaBot.The name of the conversational assistant component of the proposed system.

Django.A Python-based web framework that will be used to develop the web application.

Knowledge Base.The organized collection of pregnancy-related educational information used by the system to retrieve relevant content for user questions.

Guest User.A visitor who will access the system without creating an account and whose conversation context will be temporary.

Registered User.A person who will create an account and log in to access account-based features, including a pregnancy profile and saved conversation history.

Pregnancy Profile.The section of the system where a registered user will enter and update relevant profile information.

Warning Signs.Symptoms or conditions that may require prompt assessment or care from a qualified healthcare professional.

Administrator.An authorized user who will manage pregnancy information and related system content.


members
Bryan jay escalante
jilwin estoya
beso kenneth
